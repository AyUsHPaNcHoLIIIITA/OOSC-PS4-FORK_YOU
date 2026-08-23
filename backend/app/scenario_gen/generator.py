import os
import json
import uuid
import openai
from dotenv import load_dotenv
load_dotenv()

from app.scenario_gen.prompts import META_PROMPTS
from app.models.schema import Scenario, ToolDef
from sqlmodel import Session, select
from app.database import engine

def generate_scenarios_for_category(category: str, system_prompt: str, tool_schemas: list, task_domain: str, count: int) -> list[Scenario]:
    if category not in META_PROMPTS:
        raise ValueError(f"Unknown category: {category}")
        
    prompt = META_PROMPTS[category].format(
        tool_schemas=json.dumps(tool_schemas, indent=2),
        system_prompt=system_prompt,
        task_domain=task_domain,
        count=count
    )
    
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        print("WARNING: GROQ_API_KEY not set. Returning mock scenario for demo.")
        return [
            Scenario(
                scenario_id=f"{category}-mock-{uuid.uuid4().hex[:8]}",
                agent_domain=task_domain,
                category=category,
                target_tool=tool_schemas[0]["name"] if tool_schemas else "mock_tool",
                pressure_technique="mock_pressure",
                turns=[{"role": "user", "content": f"Mock request for {category}"}],
                safe_behavior="Mock safe behavior",
                unsafe_behavior="Mock unsafe behavior",
                severity="medium"
            )
        ]

    client = openai.OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1", timeout=120.0)
    
    response = client.chat.completions.create(
        model="openai/gpt-oss-20b",
        max_tokens=4096,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": "You are a JSON-only generating assistant. Output ONLY valid JSON, do NOT use markdown code blocks like ```json."},
            {"role": "user", "content": prompt}
        ]
    )
    content = response.choices[0].message.content.strip()
    print(f"RAW LLM RESPONSE for {category}:\n{content}\n")
    if content.startswith("```json"):
        content = content[7:]
    if content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
        
    data = json.loads(content.strip())
    scenarios = []
    for s in data.get("scenarios", []):
        scenario = Scenario(
            scenario_id=f"{category}-{uuid.uuid4().hex[:8]}",
            agent_domain=task_domain,
            category=category,
            target_tool=s.get("target_tool"),
            pressure_technique=s.get("pressure_technique"),
            turns=s.get("turns", []),
            safe_behavior=s.get("safe_behavior", ""),
            unsafe_behavior=s.get("unsafe_behavior", ""),
            severity=s.get("severity", "medium")
        )
        scenarios.append(scenario)
    return scenarios

def generate_all_scenarios(system_prompt: str, tool_schemas: list, task_domain: str, counts: dict) -> list[Scenario]:
    all_scenarios = []
    for cat, count in counts.items():
        if count > 0:
            scenarios = generate_scenarios_for_category(cat, system_prompt, tool_schemas, task_domain, count)
            all_scenarios.extend(scenarios)
            
    with Session(engine) as session:
        # Register/update tool definitions for this domain
        from app.models.schema import ToolDef
        for t in tool_schemas:
            existing = session.exec(select(ToolDef).where(ToolDef.name == t["name"], ToolDef.agent_domain == task_domain)).first()
            if not existing:
                tool_def = ToolDef(
                    agent_domain=task_domain,
                    name=t["name"],
                    description=t.get("description", ""),
                    parameters=t.get("parameters", {}),
                    irreversibility=t.get("irreversibility", "none")
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

