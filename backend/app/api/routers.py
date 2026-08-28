from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from app.scenario_gen.generator import generate_all_scenarios
from app.scenario_gen.analyzer import analyze_agent
from app.harness.runner import execute_scenarios
from app.classifier.rules import run_rule_based_checks
from app.classifier.judge import run_llm_judge
from app.guardrail.scorer import compute_guardrail_metrics
from app.scorecard.aggregator import generate_scorecard, evaluate_gate
from app.scorecard.badge import build_badge_svg, badge_for_scorecard
from app.scorecard.report import build_report_html, build_report_markdown
from app.models.schema import Scenario, Run, Verdict, GuardrailMetric, Scorecard
from sqlmodel import Session, select
from app.database import engine



router = APIRouter()

class GenerateScenariosRequest(BaseModel):
    system_prompt: str
    tools: List[Dict[str, Any]]
    task_domain: str
    count_per_category: Dict[str, int]

@router.post("/api/scenarios/generate")
def generate_scenarios(req: GenerateScenariosRequest):
    try:
        scenarios = generate_all_scenarios(
            system_prompt=req.system_prompt,
            tool_schemas=req.tools,
            task_domain=req.task_domain,
            counts=req.count_per_category
        )
        return scenarios
    except Exception as e:
        print("API Error:", str(e))
        raise HTTPException(status_code=500, detail=str(e))

class ExecuteRunsRequest(BaseModel):
    scenario_ids: List[str]
    agent_version: str
    system_prompt: str
    tools: List[Dict[str, Any]]
    samples: int = 1

@router.post("/api/runs/execute", response_model=List[Run])
async def execute_runs(req: ExecuteRunsRequest):
    try:
        runs = await execute_scenarios(
            scenario_ids=req.scenario_ids,
            agent_version=req.agent_version,
            system_prompt=req.system_prompt,
            tool_schemas=req.tools,
            samples=req.samples
        )
        return runs
    except Exception as e:
        print("API Error:", str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/runs/{run_id}", response_model=Run)
def get_run(run_id: str):
    with Session(engine) as session:
        run = session.exec(select(Run).where(Run.run_id == run_id)).first()
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        return run

class ReplayRunRequest(BaseModel):
    system_prompt: str
    tools: List[Dict[str, Any]]

@router.post("/api/runs/replay/{run_id}")
async def replay_run_endpoint(run_id: str, req: ReplayRunRequest):
    try:
        with Session(engine) as session:
            orig_run = session.exec(select(Run).where(Run.run_id == run_id)).first()
            if not orig_run:
                raise HTTPException(status_code=404, detail="Original run not found")
            scenario = session.exec(select(Scenario).where(Scenario.scenario_id == orig_run.scenario_id)).first()
            if not scenario:
                raise HTTPException(status_code=404, detail="Scenario not found")

        # Import run_scenario
        from app.harness.runner import run_scenario
        replayed_run = await run_scenario(
            scenario_id=orig_run.scenario_id,
            agent_version=orig_run.agent_version,
            system_prompt=req.system_prompt,
            tool_schemas=req.tools
        )

        verdict = run_rule_based_checks(replayed_run, scenario, req.tools)
        if not verdict:
            verdict = run_llm_judge(replayed_run, scenario)

        with Session(engine) as session:
            session.add(verdict)
            session.commit()
            session.refresh(verdict)

        return {
            "replayed_run": replayed_run,
            "verdict": verdict
        }
    except Exception as e:
        print("Replay Error:", str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/scenarios/list", response_model=List[Scenario])
def list_scenarios():
    with Session(engine) as session:
        scenarios = session.exec(select(Scenario)).all()
        return scenarios


class ClassifyRequest(BaseModel):
    run_ids: List[str]
    tools: List[Dict[str, Any]]

@router.post("/api/classify", response_model=List[Verdict])
def classify_runs(req: ClassifyRequest):
    verdicts = []
    with Session(engine) as session:
        for run_id in req.run_ids:
            run = session.exec(select(Run).where(Run.run_id == run_id)).first()
            if not run:
                continue
            scenario = session.exec(select(Scenario).where(Scenario.scenario_id == run.scenario_id)).first()
            if not scenario:
                continue
                
            verdict = run_rule_based_checks(run, scenario, req.tools)
            if not verdict:
                verdict = run_llm_judge(run, scenario)
                
            session.add(verdict)
            verdicts.append(verdict)
        session.commit()
        for v in verdicts:
            session.refresh(v)
    return verdicts

@router.get("/api/guardrail/{agent_version}", response_model=List[GuardrailMetric])
def get_guardrail(agent_version: str):
    metrics = compute_guardrail_metrics(agent_version)
    return metrics

@router.get("/api/scorecard/{agent_version}", response_model=Scorecard)
def get_scorecard(agent_version: str, previous_version: str = None):
    scorecard = generate_scorecard(agent_version, previous_version)
    return scorecard

class CiGateRequest(BaseModel):
    agent_version: str
    system_prompt: Optional[str] = None
    tools: List[Dict[str, Any]] = []
    task_domain: Optional[str] = None
    previous_version: Optional[str] = None
    min_score: int = 75

@router.post("/api/ci/gate")
async def ci_gate(req: CiGateRequest):
    """CI ship-gate. If an agent spec (system_prompt + tools) is supplied, runs the
    full pipeline first (generate -> execute -> classify) so CI can gate from
    scratch; otherwise gates the existing evaluation for the version."""
    try:
        if req.system_prompt and req.tools:
            domain = req.task_domain or "general"
            analysis = analyze_agent(
                system_prompt=req.system_prompt,
                tool_schemas=req.tools,
                task_domain=domain,
            )
            counts = analysis.get("recommended_counts", {
                "happy_path": 1,
                "destructive_action_pressure": 1,
                "direct_injection": 1,
                "indirect_injection": 1,
            })
            scenarios = generate_all_scenarios(
                system_prompt=req.system_prompt,
                tool_schemas=req.tools,
                task_domain=domain,
                counts=counts,
            )
            scenario_ids = [s.scenario_id for s in scenarios]
            runs = await execute_scenarios(
                scenario_ids=scenario_ids,
                agent_version=req.agent_version,
                system_prompt=req.system_prompt,
                tool_schemas=req.tools,
            )
            # Classify inline (mirror /api/classify's rules -> judge cascade).
            with Session(engine) as session:
                for run in runs:
                    scenario = session.exec(select(Scenario).where(Scenario.scenario_id == run.scenario_id)).first()
                    if not scenario:
                        continue
                    verdict = run_rule_based_checks(run, scenario, req.tools)
                    if not verdict:
                        verdict = run_llm_judge(run, scenario)
                    session.add(verdict)
                session.commit()

        scorecard = generate_scorecard(req.agent_version, req.previous_version)
        gate = evaluate_gate(scorecard, req.min_score)
        return {"gate": gate, "scorecard": scorecard}
    except Exception as e:
        print("CI Gate Error:", str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/badge/{agent_version}.svg")
def get_badge(agent_version: str):
    """Embeddable SVG reliability badge. Emits a gray 'unrated' badge for versions
    with no runs instead of erroring, so a README badge never 404s."""
    with Session(engine) as session:
        has_runs = session.exec(select(Run).where(Run.agent_version == agent_version)).first()
    if not has_runs:
        svg = build_badge_svg("AgentCI", "unrated", "#9ca3af")
    else:
        scorecard = generate_scorecard(agent_version)
        label, message, color = badge_for_scorecard(scorecard)
        svg = build_badge_svg(label, message, color)
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={"Cache-Control": "no-cache, max-age=0"},
    )

@router.get("/api/report/{agent_version}.html")
def get_report_html(agent_version: str, previous_version: str = None):
    """Feature 4: standalone printable HTML reliability report for a version."""
    scorecard = generate_scorecard(agent_version, previous_version)
    return Response(content=build_report_html(scorecard), media_type="text/html")

@router.get("/api/report/{agent_version}.md")
def get_report_markdown(agent_version: str, previous_version: str = None):
    """Feature 4: Markdown flavor of the report for pasting into PRs / issues."""
    scorecard = generate_scorecard(agent_version, previous_version)
    return Response(content=build_report_markdown(scorecard), media_type="text/plain; charset=utf-8")

class AgentAnalyzeRequest(BaseModel):
    system_prompt: str
    tools: List[Dict[str, Any]]
    task_domain: str

@router.post("/api/agent/analyze")
def analyze_agent_endpoint(req: AgentAnalyzeRequest):
    try:
        analysis = analyze_agent(
            system_prompt=req.system_prompt,
            tool_schemas=req.tools,
            task_domain=req.task_domain
        )
        return analysis
    except Exception as e:
        print("Analysis Error:", str(e))
        raise HTTPException(status_code=500, detail=str(e))

class AutoGenerateRequest(BaseModel):
    system_prompt: str
    tools: List[Dict[str, Any]]
    task_domain: str
    override_counts: Dict[str, int] = None

@router.post("/api/agent/auto-generate")
def auto_generate_scenarios_endpoint(req: AutoGenerateRequest):
    try:
        # Step 1: Analyze capabilities and threat surface
        analysis = analyze_agent(
            system_prompt=req.system_prompt,
            tool_schemas=req.tools,
            task_domain=req.task_domain
        )
        
        counts = req.override_counts or analysis.get("recommended_counts", {
            "happy_path": 1,
            "destructive_action_pressure": 1,
            "direct_injection": 1,
            "indirect_injection": 1
        })
        
        # Step 2: Generate agent-tailored scenarios
        scenarios = generate_all_scenarios(
            system_prompt=req.system_prompt,
            tool_schemas=req.tools,
            task_domain=req.task_domain,
            counts=counts
        )
        
        return {
            "analysis": analysis,
            "scenarios": scenarios
        }
    except Exception as e:
        print("Auto-Generate Error:", str(e))
        raise HTTPException(status_code=500, detail=str(e))


