import json
import uuid
import time
import asyncio
from datetime import datetime
import openai
from typing import List, Dict, Any
from app.models.schema import Run, Scenario
from app.harness.mock_tools import simulate_tool_response
from app.harness.sandbox import StatefulSandbox
from app.llm_utils import get_async_client, get_model_name
from sqlmodel import Session, select
from app.database import engine

# Per-user-turn tool budget: >=3 so the runner can reproduce (and the loop rule
# can detect) an agent stuck calling the same tool repeatedly.
MAX_TOOL_ITERS_PER_TURN = 5
# Global ceiling on model invocations per run, to bound cost / runaway loops.
MAX_MODEL_CALLS = 12


def convert_tools_to_openai(tool_schemas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    openai_tools = []
    for t in tool_schemas:
        openai_tools.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": {
                    "type": "object",
                    "properties": {k: {"type": v} for k, v in t.get("parameters", {}).items()},
                }
            }
        })
    return openai_tools


async def _call_model_with_retry(client, messages, openai_tools):
    """Single model call with linear backoff on rate limits. Returns the response
    or None if all attempts are exhausted."""
    for attempt in range(4):
        try:
            return await client.chat.completions.create(
                model=get_model_name(),
                max_tokens=1024,
                messages=messages,
                tools=openai_tools if openai_tools else None,
            )
        except openai.RateLimitError:
            if attempt == 3:
                raise
            await asyncio.sleep(2.0 * (attempt + 1))
    return None


async def run_scenario(scenario_id: str, agent_version: str, system_prompt: str, tool_schemas: List[Dict[str, Any]]) -> Run:
    with Session(engine) as session:
        scenario = session.exec(select(Scenario).where(Scenario.scenario_id == scenario_id)).first()
        if not scenario:
            raise ValueError(f"Scenario {scenario_id} not found")

    client = get_async_client()
    if client is None:
        return mock_run(scenario, agent_version, tool_schemas)

    openai_tools = convert_tools_to_openai(tool_schemas)
    tool_map = {t["name"]: t for t in tool_schemas}
    sandbox = StatefulSandbox(
        domain=scenario.agent_domain,
        scenario_id=scenario.scenario_id,
        category=scenario.category,
        target_tool=scenario.target_tool,
    )

    messages: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    steps: List[Dict[str, Any]] = []
    started_at = datetime.utcnow()
    step_counter = 0
    model_calls = 0

    def record_step(entry: Dict[str, Any]) -> None:
        nonlocal step_counter
        entry["step"] = step_counter
        steps.append(entry)
        step_counter += 1

    async def agent_respond() -> None:
        """Let the agent act on the conversation so far until it produces a
        plain-text reply (turn settled), executing any tool calls against the
        sandbox in between. Stops on a settled reply, when the per-turn tool
        budget is exhausted, or when the global model-call cap is reached."""
        nonlocal model_calls
        for _ in range(MAX_TOOL_ITERS_PER_TURN):
            if model_calls >= MAX_MODEL_CALLS:
                return
            try:
                start_time = time.time()
                response = await _call_model_with_retry(client, messages, openai_tools)
                latency_ms = int((time.time() - start_time) * 1000)
            except Exception as e:
                print(f"Error in runner model call: {e}")
                return
            if response is None:
                return
            model_calls += 1
            message = response.choices[0].message

            if message.tool_calls:
                # OpenAI protocol: a single assistant message carrying ALL tool
                # calls, then one tool message per call.
                messages.append({
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                        }
                        for tc in message.tool_calls
                    ],
                })

                for i, tc in enumerate(message.tool_calls):
                    try:
                        args = json.loads(tc.function.arguments)
                    except Exception:
                        args = {}
                    # One assistant step per tool call (preserves the single
                    # `tool_call` step shape the classifier expects). Text and
                    # model latency are attributed to the first call only.
                    record_step({
                        "role": "assistant",
                        "content": message.content if i == 0 else None,
                        "tool_call": {"name": tc.function.name, "args": args},
                        "latency_ms": latency_ms if i == 0 else 0,
                    })
                    start_tool_time = time.time()
                    tool_result = simulate_tool_response(
                        tc.function.name, args, tool_map.get(tc.function.name, {}), scenario, sandbox=sandbox
                    )
                    tool_latency = int((time.time() - start_tool_time) * 1000)
                    record_step({"role": "tool", "result": tool_result, "latency_ms": tool_latency})
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(tool_result),
                    })
                # Loop again so the agent can react to the tool output.
                continue

            # Plain-text reply → this turn is settled.
            text_content = message.content or ""
            record_step({"role": "assistant", "content": text_content, "latency_ms": latency_ms})
            messages.append({"role": "assistant", "content": text_content})
            return

    saw_user_turn = False
    for turn in scenario.turns:
        role = turn.get("role", "user")
        if role in ["agent", "bot", "ai"]:
            role = "assistant"
        content = turn.get("content", "")

        if role == "assistant":
            # Pre-scripted assistant context (e.g. goal_drift) — inject as
            # history, don't generate a response for it.
            messages.append({"role": "assistant", "content": content})
            record_step({"role": "assistant", "content": content})
            continue

        # A user (or any non-assistant) turn drives a fresh agent response.
        saw_user_turn = True
        messages.append({"role": "user", "content": content})
        record_step({"role": "user", "content": content})
        await agent_respond()
        if model_calls >= MAX_MODEL_CALLS:
            break

    # Edge case: a scenario with no user turns still gets one agent response.
    if not saw_user_turn and len(messages) > 1 and model_calls < MAX_MODEL_CALLS:
        await agent_respond()

    run = Run(
        run_id=f"run-{uuid.uuid4().hex}",
        scenario_id=scenario_id,
        agent_version=agent_version,
        started_at=started_at,
        steps=steps,
    )

    with Session(engine) as session:
        session.add(run)
        session.commit()
        session.refresh(run)

    return run


def mock_run(scenario, agent_version, tool_schemas):
    steps = []
    for idx, turn in enumerate(scenario.turns):
        steps.append({
            "step": idx,
            "role": turn.get("role", "user"),
            "content": turn.get("content", ""),
        })
    steps.append({
        "step": len(scenario.turns),
        "role": "assistant",
        "tool_call": {"name": scenario.target_tool or (tool_schemas[0]["name"] if tool_schemas else "mock_tool"), "args": {}},
        "latency_ms": 100
    })
    steps.append({
        "step": len(scenario.turns) + 1,
        "role": "tool",
        "result": {"status": "mock success"},
        "latency_ms": 20
    })
    steps.append({
        "step": len(scenario.turns) + 2,
        "role": "assistant",
        "content": "I have completed the mock tool call.",
        "latency_ms": 100
    })

    run = Run(
        run_id=f"run-{uuid.uuid4().hex}",
        scenario_id=scenario.scenario_id,
        agent_version=agent_version,
        started_at=datetime.utcnow(),
        steps=steps
    )

    with Session(engine) as session:
        session.add(run)
        session.commit()
        session.refresh(run)
    return run


async def execute_scenarios(scenario_ids: List[str], agent_version: str, system_prompt: str, tool_schemas: List[Dict[str, Any]]) -> List[Run]:
    runs = []
    for sid in scenario_ids:
        run = await run_scenario(sid, agent_version, system_prompt, tool_schemas)
        runs.append(run)
        await asyncio.sleep(0.5)
    return runs
