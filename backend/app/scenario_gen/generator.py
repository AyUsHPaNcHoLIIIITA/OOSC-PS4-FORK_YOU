import json
import uuid
import time
import openai
from dotenv import load_dotenv
load_dotenv()

from app.scenario_gen.prompts import META_PROMPTS
from app.models.schema import Scenario, ToolDef
from app.llm_utils import get_sync_client, get_model_name, parse_json_response
from sqlmodel import Session, select
from app.database import engine

_GENERATOR_SYSTEM = "You are a JSON-only generating assistant. Output ONLY valid JSON, do NOT use markdown code blocks like ```json."


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

    # Retry transient rate limits with linear backoff (mirrors the runner).
    response = None
    for attempt in range(4):
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
        except openai.RateLimitError:
            if attempt == 3:
                raise
            time.sleep(2.0 * (attempt + 1))

    data = parse_json_response(response.choices[0].message.content)
    scenarios = []
    for s in data.get("scenarios", []):
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
    return scenarios


def generate_all_scenarios(system_prompt: str, tool_schemas: list, task_domain: str, counts: dict) -> list[Scenario]:
    all_scenarios = []
    for cat, count in counts.items():
        if count <= 0:
            continue
        try:
            scenarios = generate_scenarios_for_category(cat, system_prompt, tool_schemas, task_domain, count)
            all_scenarios.extend(scenarios)
        except Exception as e:
            # One malformed category response should not abort the whole batch.
            print(f"WARNING: scenario generation failed for category '{cat}' ({e}); skipping.")
            continue

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
