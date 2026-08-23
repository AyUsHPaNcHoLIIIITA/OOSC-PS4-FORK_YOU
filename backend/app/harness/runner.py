import os
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
from sqlmodel import Session, select
from app.database import engine

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

async def run_scenario(scenario_id: str, agent_version: str, system_prompt: str, tool_schemas: List[Dict[str, Any]]) -> Run:
    with Session(engine) as session:
        scenario = session.exec(select(Scenario).where(Scenario.scenario_id == scenario_id)).first()
        if not scenario:
            raise ValueError(f"Scenario {scenario_id} not found")
            
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return mock_run(scenario, agent_version, tool_schemas)
        
    client = openai.AsyncOpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")
    openai_tools = convert_tools_to_openai(tool_schemas)
    
    steps = []
    messages = [{"role": "system", "content": system_prompt}]
    
    for idx, turn in enumerate(scenario.turns):
        role = turn.get("role", "user")
        if role in ["agent", "bot", "ai"]:
            role = "assistant"
        content = turn.get("content", "")
        messages.append({"role": role, "content": content})
        steps.append({
            "step": idx,
            "role": role,
            "content": content
        })
        
    step_counter = len(scenario.turns)
    started_at = datetime.utcnow()
    MAX_TURNS = 10
    sandbox = StatefulSandbox(domain=scenario.agent_domain, scenario_id=scenario.scenario_id, category=scenario.category, target_tool=scenario.target_tool)
    tool_map = {t["name"]: t for t in tool_schemas}
    
    for _ in range(MAX_TURNS):
        try:
            start_time = time.time()
            response = None
            for attempt in range(4):
                try:
                    response = await client.chat.completions.create(
                        model="openai/gpt-oss-20b",
                        max_tokens=1024,
                        messages=messages,
                        tools=openai_tools if openai_tools else None
                    )
                    break
                except openai.RateLimitError:
                    if attempt == 3:
                        raise
                    await asyncio.sleep(2.0 * (attempt + 1))
            
            if not response:
                break
                
            latency_ms = int((time.time() - start_time) * 1000)
            message = response.choices[0].message
            
            if message.tool_calls:
                tool_call = message.tool_calls[0]
                text_content = message.content
                
                try:
                    args = json.loads(tool_call.function.arguments)
                except Exception:
                    args = {}
                
                steps.append({
                    "step": step_counter,
                    "role": "assistant",
                    "content": text_content,
                    "tool_call": {"name": tool_call.function.name, "args": args},
                    "latency_ms": latency_ms
                })
                step_counter += 1
                
                assistant_message = {
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [
                        {
                            "id": tool_call.id,
                            "type": "function",
                            "function": {
                                "name": tool_call.function.name,
                                "arguments": tool_call.function.arguments
                            }
                        }
                    ]
                }
                messages.append(assistant_message)
                
                start_tool_time = time.time()
                tool_result = simulate_tool_response(tool_call.function.name, args, tool_map.get(tool_call.function.name, {}), scenario, sandbox=sandbox)
                tool_latency = int((time.time() - start_tool_time) * 1000)
                
                steps.append({
                    "step": step_counter,
                    "role": "tool",
                    "result": tool_result,
                    "latency_ms": tool_latency
                })
                step_counter += 1
                
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(tool_result)
                })
                
            else:
                text_content = message.content
                steps.append({
                    "step": step_counter,
                    "role": "assistant",
                    "content": text_content,
                    "latency_ms": latency_ms
                })
                break
                
        except Exception as e:
            print(f"Error in runner loop: {e}")
            break
            
    run = Run(
        run_id=f"run-{uuid.uuid4().hex}",
        scenario_id=scenario_id,
        agent_version=agent_version,
        started_at=started_at,
        steps=steps
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
            "role": turn["role"],
            "content": turn["content"]
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
