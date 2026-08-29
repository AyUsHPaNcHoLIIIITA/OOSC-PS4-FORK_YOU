import json
import uuid
import time
from typing import Any, Optional

import openai
from dotenv import load_dotenv
load_dotenv()

from app.scenario_gen.prompts import META_PROMPTS
from app.models.schema import Scenario, ToolDef
from app.llm_utils import get_sync_client, get_model_name, parse_json_response
from sqlmodel import Session, select
from app.database import engine

_GENERATOR_SYSTEM = "You are a JSON-only generating assistant. Output ONLY valid JSON, do NOT use markdown code blocks like ```json."

# Transient failures worth retrying: free-tier TPM rate limits, timeouts, and
# upstream 5xx. A bursty full-pipeline run is the usual trigger for these.
# Built defensively so a missing attribute in some openai version can never
# raise at import time and take down the whole backend.
_MAX_ATTEMPTS = 5
_TRANSIENT_ERRORS = tuple(
    exc for exc in (
        getattr(openai, "RateLimitError", None),
        getattr(openai, "APITimeoutError", None),
        getattr(openai, "APIConnectionError", None),
        getattr(openai, "InternalServerError", None),
    )
    if isinstance(exc, type)
) or (openai.RateLimitError,)


def _retry_after_seconds(err: Exception) -> Optional[float]:
    """Best-effort parse of a Retry-After header from an OpenAI/Groq error."""
    resp = getattr(err, "response", None)
    headers = getattr(resp, "headers", None) or {}
    val = headers.get("retry-after") or headers.get("Retry-After")
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def _extract_scenarios(data: Any) -> list:
    """Pull the scenario list out of a model response, tolerating minor shape drift.

    Expected shape is ``{"scenarios": [...]}``, but small models occasionally drop
    the wrapper key or return the array directly. Be forgiving rather than silently
    yielding zero scenarios.
    """
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if isinstance(data.get("scenarios"), list):
            return data["scenarios"]
        # Wrapper key missing: take the first list-of-objects value.
        for v in data.values():
            if isinstance(v, list) and (not v or isinstance(v[0], dict)):
                return v
        # Or the object itself is a single scenario.
        if "turns" in data:
            return [data]
    return []


def _mock_scenario(category: str, tool_schemas: list, task_domain: str) -> Scenario:
    return Scenario(
        scenario_id=f"{category}-mock-{uuid.uuid4().hex[:8]}",
        agent_domain=task_domain,
        category=category,
        target_tool=tool_schemas[0]["name"] if tool_schemas else "mock_tool",
        pressure_technique="mock_pressure",
        turns=[{"role": "user", "content": f"Mock request for {category}"}],
        safe_behavior="Mock safe behavior",
        unsafe_behavior="Mock unsafe behavior",
        severity="medium",
    )


def generate_scenarios_for_category(category: str, system_prompt: str, tool_schemas: list, task_domain: str, count: int) -> list[Scenario]:
    if category not in META_PROMPTS:
        raise ValueError(f"Unknown category: {category}")

    prompt = META_PROMPTS[category].format(
        tool_schemas=json.dumps(tool_schemas, indent=2),
        system_prompt=system_prompt,
        task_domain=task_domain,
        count=count,
    )

    client = get_sync_client(timeout=120.0)
    if client is None:
        print("WARNING: GROQ_API_KEY not set. Returning mock scenario for demo.")
        return [_mock_scenario(category, tool_schemas, task_domain)]

    # Retry transient failures (rate limits, timeouts, upstream 5xx), honoring the
    # server's Retry-After when present so we ride out a per-minute quota window.
    response = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            response = client.chat.completions.create(
                model=get_model_name(),
                max_tokens=4096,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": _GENERATOR_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
            )
            break
        except _TRANSIENT_ERRORS as e:
            if attempt == _MAX_ATTEMPTS - 1:
                raise
            time.sleep(min(_retry_after_seconds(e) or 2.0 * (attempt + 1), 20.0))

    data = parse_json_response(response.choices[0].message.content)
    scenarios = []
    for s in _extract_scenarios(data):
        if not isinstance(s, dict):
            continue
        scenarios.append(Scenario(
            scenario_id=f"{category}-{uuid.uuid4().hex[:8]}",
            agent_domain=task_domain,
            category=category,
            target_tool=s.get("target_tool"),
            pressure_technique=s.get("pressure_technique"),
            turns=s.get("turns", []),
            safe_behavior=s.get("safe_behavior", ""),
            unsafe_behavior=s.get("unsafe_behavior", ""),
            severity=s.get("severity", "medium"),
        ))
    if not scenarios:
        # Got a response but extracted nothing — log a truncated preview so a
        # future "0 scenarios" is diagnosable (shape drift vs. genuinely empty).
        preview = (response.choices[0].message.content or "")[:500]
        print(f"WARNING: category '{category}' yielded 0 scenarios from response: {preview!r}")
    return scenarios


def generate_all_scenarios(system_prompt: str, tool_schemas: list, task_domain: str, counts: dict) -> list[Scenario]:
    all_scenarios = []
    errors = []
    attempted = 0
    for cat, count in counts.items():
        if count <= 0:
            continue
        attempted += 1
        try:
            scenarios = generate_scenarios_for_category(cat, system_prompt, tool_schemas, task_domain, count)
            all_scenarios.extend(scenarios)
        except Exception as e:
            # One malformed category response should not abort the whole batch,
            # but a total wipe-out must NOT be reported to the user as success.
            print(f"WARNING: scenario generation failed for category '{cat}' ({e}); skipping.")
            errors.append(f"{cat}: {type(e).__name__}: {e}")
            continue

    # Never return an empty list that the UI reports as "successfully generated 0".
    # If we attempted categories but produced nothing, surface a real, actionable error.
    if attempted and not all_scenarios:
        detail = " | ".join(errors) if errors else "the model returned no scenarios for any category"
        raise RuntimeError(
            "Scenario generation produced 0 scenarios. This is usually a Groq "
            "rate-limit/quota issue during a bursty run — wait ~30s and retry. "
            f"Details: {detail}"
        )

    with Session(engine) as session:
        # Register/update tool definitions for this domain
        for t in tool_schemas:
            existing = session.exec(select(ToolDef).where(ToolDef.name == t["name"], ToolDef.agent_domain == task_domain)).first()
            if not existing:
                tool_def = ToolDef(
                    agent_domain=task_domain,
                    name=t["name"],
                    description=t.get("description", ""),
                    parameters=t.get("parameters", {}),
                    irreversibility=t.get("irreversibility", "none"),
                )
                session.add(tool_def)
            else:
                existing.irreversibility = t.get("irreversibility", existing.irreversibility)
                session.add(existing)

        for s in all_scenarios:
            session.add(s)
        session.commit()
        for s in all_scenarios:
            session.refresh(s)

    return all_scenarios
