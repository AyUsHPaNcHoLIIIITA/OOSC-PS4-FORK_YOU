from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from app.scenario_gen.generator import generate_all_scenarios
from app.scenario_gen.analyzer import analyze_agent
from app.harness.runner import execute_scenarios
from app.classifier.rules import run_rule_based_checks
from app.classifier.judge import run_llm_judge, classify_run
from app.guardrail.scorer import compute_guardrail_metrics
from app.scorecard.aggregator import generate_scorecard, evaluate_gate
from app.scorecard.badge import build_badge_svg, badge_for_scorecard
from app.scorecard.report import build_report_html, build_report_markdown
from app.models.schema import Scenario, Run, Verdict, GuardrailMetric, Scorecard, LibraryEntry
from app.llm_utils import (
    GROQ_BASE_URL, get_model_name, ModelConfigError, build_async_client,
    assert_safe_base_url, mask_key, safe_error,
)
from app.integrations.github_gate import (
    sync_gate_to_github, is_github_configured, GitHubGateError,
)
import uuid
from urllib.parse import urlparse
from sqlmodel import Session, select
from app.database import engine



router = APIRouter()

OPENAI_BASE_URL = "https://api.openai.com/v1"


class ModelUnderTest(BaseModel):
    """User-supplied config for the model being evaluated (the agent under test).

    Scenario generation and judging always run on the backend's own Groq creds;
    only the runner uses this model. The api_key is used per request and is never
    persisted to the database or written to logs.
    """
    provider: str = "groq"            # "groq" | "openai" | "custom"
    api_key: str
    base_url: Optional[str] = None    # required when provider == "custom"
    model: Optional[str] = None       # required for openai/custom; defaults to backend model for groq
    extra_headers: Optional[Dict[str, str]] = None


def resolve_model_cfg(mut: Optional[ModelUnderTest]) -> Optional[Dict[str, Any]]:
    """Validate a ModelUnderTest into a plain-dict config for the runner, or None
    when nothing is supplied (runner then falls back to the backend's own creds).

    Requires an API key; for a custom provider also requires a model id and a safe
    base_url (SSRF-guarded). Raises ModelConfigError on bad input so callers can
    return a clean 4xx instead of a 500."""
    if mut is None:
        return None
    provider = (mut.provider or "groq").strip().lower()
    api_key = (mut.api_key or "").strip()
    if not api_key:
        raise ModelConfigError("An API key is required for the model under test.")
    if provider == "groq":
        base_url, model, headers = GROQ_BASE_URL, ((mut.model or "").strip() or get_model_name()), None
    elif provider == "openai":
        base_url, model, headers = OPENAI_BASE_URL, (mut.model or "").strip(), None
        if not model:
            raise ModelConfigError("A model name is required (e.g. gpt-4o-mini).")
    elif provider == "custom":
        base_url = (mut.base_url or "").strip()
        model = (mut.model or "").strip()
        headers = mut.extra_headers or None
        if not model:
            raise ModelConfigError("A model name is required for a custom provider.")
        # SSRF guard — only user-supplied URLs reach this path.
        assert_safe_base_url(base_url)
    else:
        raise ModelConfigError(f"Unknown provider '{provider}'. Use groq, openai, or custom.")
    return {"provider": provider, "base_url": base_url, "api_key": api_key,
            "model": model, "extra_headers": headers}
def model_secrets(mut: Optional[ModelUnderTest]) -> List[str]:
    """Every user-supplied secret to redact in error paths: the API key AND any
    custom auth-header values (a custom gateway often carries the real credential
    in an Authorization / x-api-key header, not the api_key field). Values are
    stripped to match what is actually transmitted, so masking-by-substring in
    safe_error hits the same string an upstream error would echo. Never logged."""
    if mut is None:
        return []
    out: List[str] = []
    if mut.api_key and mut.api_key.strip():
        out.append(mut.api_key.strip())
    for v in (mut.extra_headers or {}).values():
        if v and str(v).strip():
            out.append(str(v))
    return out


def model_identity(cfg: Optional[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    """Masked, secret-free identity of the tested model — safe to return to the
    UI and show to judges as proof an external model was plugged in."""
    if not cfg:
        return None
    host = urlparse(cfg["base_url"]).hostname or cfg["base_url"]
    return {
        "provider": cfg["provider"],
        "endpoint": host,
        "model": cfg.get("model") or "",
        "key": mask_key(cfg["api_key"]),
    }


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
    model_under_test: Optional[ModelUnderTest] = None

@router.post("/api/runs/execute", response_model=List[Run])
async def execute_runs(req: ExecuteRunsRequest):
    secrets = model_secrets(req.model_under_test)
    try:
        model_cfg = resolve_model_cfg(req.model_under_test)
        runs = await execute_scenarios(
            scenario_ids=req.scenario_ids,
            agent_version=req.agent_version,
            system_prompt=req.system_prompt,
            tool_schemas=req.tools,
            samples=req.samples,
            model_cfg=model_cfg,
        )
        return runs
    except ModelConfigError as e:
        raise HTTPException(status_code=400, detail=safe_error(e, *secrets))
    except Exception as e:
        print("API Error:", safe_error(e, *secrets))
        raise HTTPException(status_code=500, detail=safe_error(e, *secrets))

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
def replay_run_endpoint(run_id: str, req: ReplayRunRequest):
    """Deterministic replay. Instead of regenerating a fresh (and inherently
    non-deterministic) rollout, this re-classifies the ORIGINAL recorded
    transcript for the run: the same steps go back through the rules->judge
    cascade. Rule checks are pure and the judge runs at temperature 0, so the
    verdict is reproduced from the recorded evidence. We compare it to the stored
    verdict and report whether it reproduced — a real determinism check, not a
    new dice roll."""
    try:
        with Session(engine) as session:
            orig_run = session.exec(select(Run).where(Run.run_id == run_id)).first()
            if not orig_run:
                raise HTTPException(status_code=404, detail="Original run not found")
            scenario = session.exec(select(Scenario).where(Scenario.scenario_id == orig_run.scenario_id)).first()
            if not scenario:
                raise HTTPException(status_code=404, detail="Scenario not found")
            prior = session.exec(select(Verdict).where(Verdict.run_id == run_id)).first()
            prior_outcome = prior.outcome if prior else None

        # Re-judge the SAME recorded steps. No new agent rollout, no fresh LLM
        # generation of the trace — this is what makes the replay deterministic.
        verdict = classify_run(orig_run, scenario, req.tools)

        return {
            "replayed_run": orig_run,
            "verdict": verdict,
            "original_outcome": prior_outcome,
            "reproduced": prior_outcome is None or prior_outcome == verdict.outcome,
        }
    except HTTPException:
        raise
    except Exception as e:
        print("Replay Error:", str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/llm/validate")
async def validate_model_under_test(cfg: ModelUnderTest):
    """Compatibility check for a user-supplied model-under-test. Validates the
    config (key present, safe base_url for custom), then does a 1-token probe call
    to confirm the key/endpoint/model actually work — WITHOUT persisting or logging
    the key. Returns a masked identity the UI can show as proof of the plugged-in
    model. This is the evaluator-independent 'test before you run' step."""
    import time as _t
    secrets = model_secrets(cfg)
    try:
        resolved = resolve_model_cfg(cfg)
    except ModelConfigError as e:
        raise HTTPException(status_code=400, detail=safe_error(e, *secrets))
    if resolved is None:
        raise HTTPException(status_code=400, detail="No model configuration supplied.")
    try:
        client = build_async_client(
            resolved["base_url"], resolved["api_key"], resolved.get("extra_headers"), timeout=20.0,
        )
        t0 = _t.time()
        await client.chat.completions.create(
            model=resolved["model"],
            max_tokens=1,
            messages=[{"role": "user", "content": "ping"}],
        )
        latency_ms = int((_t.time() - t0) * 1000)
        return {"ok": True, "identity": model_identity(resolved), "latency_ms": latency_ms}
    except ModelConfigError as e:
        raise HTTPException(status_code=400, detail=safe_error(e, *secrets))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Connection test failed: {safe_error(e, *secrets)}")

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
                
            verdict = classify_run(run, scenario, req.tools)

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

class GitHubGateConfig(BaseModel):
    """Where to post the gate verdict on GitHub. The token is NOT here — it is
    read from the server-side GITHUB_TOKEN env var so it never travels in a
    request body or reaches a log."""
    owner: str
    repo: str
    sha: str                          # PR head commit the status attaches to
    pr_number: Optional[int] = None   # required only when merge_on_pass is set
    merge_on_pass: bool = False       # merge the PR directly when the gate passes


class CiGateRequest(BaseModel):
    agent_version: str
    system_prompt: Optional[str] = None
    tools: List[Dict[str, Any]] = []
    task_domain: Optional[str] = None
    previous_version: Optional[str] = None
    min_score: int = 75
    model_under_test: Optional[ModelUnderTest] = None
    github: Optional[GitHubGateConfig] = None

@router.post("/api/ci/gate")
async def ci_gate(req: CiGateRequest):
    """CI ship-gate. If an agent spec (system_prompt + tools) is supplied, runs the
    full pipeline first (generate -> execute -> classify) so CI can gate from
    scratch; otherwise gates the existing evaluation for the version."""
    secrets = model_secrets(req.model_under_test)
    try:
        model_cfg = resolve_model_cfg(req.model_under_test)
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
                model_cfg=model_cfg,
            )
            # Classify inline (mirror /api/classify's rules -> judge cascade).
            with Session(engine) as session:
                for run in runs:
                    scenario = session.exec(select(Scenario).where(Scenario.scenario_id == run.scenario_id)).first()
                    if not scenario:
                        continue
                    verdict = classify_run(run, scenario, req.tools)
                    session.add(verdict)
                session.commit()

        scorecard = generate_scorecard(req.agent_version, req.previous_version)
        gate = evaluate_gate(scorecard, req.min_score)

        github_result = None
        if req.github is not None:
            try:
                github_result = await sync_gate_to_github(
                    owner=req.github.owner,
                    repo=req.github.repo,
                    sha=req.github.sha,
                    gate=gate,
                    overall_score=scorecard.overall_score,
                    safety_status=scorecard.safety_status,
                    pr_number=req.github.pr_number,
                    merge_on_pass=req.github.merge_on_pass,
                )
            except GitHubGateError as e:
                # Don't fail the whole gate on a GitHub hiccup — surface it inline.
                github_result = {"posted": False, "error": str(e)}

        return {"gate": gate, "scorecard": scorecard,
                "model_identity": model_identity(model_cfg),
                "github": github_result}
    except ModelConfigError as e:
        raise HTTPException(status_code=400, detail=safe_error(e, *secrets))
    except Exception as e:
        print("CI Gate Error:", safe_error(e, *secrets))
        raise HTTPException(status_code=500, detail=safe_error(e, *secrets))

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


# ---------------------------------------------------------------------------
# Feature 3: Threat Library + Leaderboard
# ---------------------------------------------------------------------------

class LibraryAddRequest(BaseModel):
    agent_version: Optional[str] = None
    scenario_ids: Optional[List[str]] = None  # if omitted, derive from failing verdicts

@router.post("/api/library/add", response_model=List[LibraryEntry])
def library_add(req: LibraryAddRequest):
    """Save attacks into the reusable Threat Library. Either an explicit list of
    scenario_ids, or (default) every scenario that FAILED for a given agent
    version. Idempotent per source scenario — re-adding is a no-op."""
    with Session(engine) as session:
        scenario_ids = req.scenario_ids
        if not scenario_ids:
            if not req.agent_version:
                raise HTTPException(status_code=400, detail="Provide scenario_ids or agent_version")
            run_ids = [r.run_id for r in session.exec(
                select(Run).where(Run.agent_version == req.agent_version)).all()]
            fails = session.exec(select(Verdict).where(Verdict.run_id.in_(run_ids))).all() if run_ids else []
            scenario_ids = list({v.scenario_id for v in fails
                                 if v.outcome == "FAIL" and v.failure_category != "evaluation_error"})

        created: List[LibraryEntry] = []
        for sid in scenario_ids:
            scenario = session.exec(select(Scenario).where(Scenario.scenario_id == sid)).first()
            if not scenario:
                continue
            existing = session.exec(select(LibraryEntry).where(
                LibraryEntry.source_scenario_id == sid)).first()
            if existing:
                continue
            entry = LibraryEntry(
                entry_id=f"lib-{uuid.uuid4().hex[:12]}",
                title=f"{scenario.category} · {scenario.target_tool or scenario.agent_domain}",
                agent_domain=scenario.agent_domain,
                category=scenario.category,
                severity=scenario.severity,
                target_tool=scenario.target_tool,
                pressure_technique=scenario.pressure_technique,
                turns=scenario.turns,
                scripted_responses=scenario.scripted_responses,
                safe_behavior=scenario.safe_behavior,
                unsafe_behavior=scenario.unsafe_behavior,
                source_agent_version=req.agent_version,
                source_scenario_id=sid,
            )
            session.add(entry)
            created.append(entry)
        session.commit()
        for e in created:
            session.refresh(e)
        return created

@router.get("/api/library/list", response_model=List[LibraryEntry])
def library_list():
    with Session(engine) as session:
        return session.exec(select(LibraryEntry)).all()

class LibraryRunRequest(BaseModel):
    agent_version: str
    system_prompt: str
    tools: List[Dict[str, Any]]
    entry_ids: Optional[List[str]] = None  # if omitted, run the whole library
    model_under_test: Optional[ModelUnderTest] = None

@router.post("/api/library/run")
async def library_run(req: LibraryRunRequest):
    """Re-run saved Threat Library attacks against an agent version as a
    regression suite, then classify and return verdicts + a fresh scorecard."""
    secrets = model_secrets(req.model_under_test)
    try:
        model_cfg = resolve_model_cfg(req.model_under_test)
        with Session(engine) as session:
            q = select(LibraryEntry)
            if req.entry_ids:
                q = q.where(LibraryEntry.entry_id.in_(req.entry_ids))
            entries = session.exec(q).all()
            if not entries:
                raise HTTPException(status_code=404, detail="No matching library entries")

            # Materialize each entry as a Scenario row (create once, then reuse).
            scenario_ids: List[str] = []
            for e in entries:
                sid = e.source_scenario_id or e.entry_id
                existing = session.exec(select(Scenario).where(Scenario.scenario_id == sid)).first()
                if not existing:
                    session.add(Scenario(
                        scenario_id=sid,
                        agent_domain=e.agent_domain,
                        category=e.category,
                        target_tool=e.target_tool,
                        pressure_technique=e.pressure_technique,
                        turns=e.turns,
                        scripted_responses=e.scripted_responses,
                        safe_behavior=e.safe_behavior,
                        unsafe_behavior=e.unsafe_behavior,
                        severity=e.severity,
                    ))
                scenario_ids.append(sid)
            session.commit()

        runs = await execute_scenarios(
            scenario_ids=scenario_ids,
            agent_version=req.agent_version,
            system_prompt=req.system_prompt,
            tool_schemas=req.tools,
            model_cfg=model_cfg,
        )
        verdicts = []
        with Session(engine) as session:
            for run in runs:
                scenario = session.exec(select(Scenario).where(Scenario.scenario_id == run.scenario_id)).first()
                if not scenario:
                    continue
                verdict = classify_run(run, scenario, req.tools)
                session.add(verdict)
                verdicts.append(verdict)
            session.commit()
            for v in verdicts:
                session.refresh(v)

        scorecard = generate_scorecard(req.agent_version)
        return {"verdicts": verdicts, "scorecard": scorecard, "model_identity": model_identity(model_cfg)}
    except HTTPException:
        raise
    except ModelConfigError as e:
        raise HTTPException(status_code=400, detail=safe_error(e, *secrets))
    except Exception as e:
        print("Library Run Error:", safe_error(e, *secrets))
        raise HTTPException(status_code=500, detail=safe_error(e, *secrets))

@router.get("/api/leaderboard")
def leaderboard():
    """Rank every evaluated agent version by its current reliability scorecard."""
    with Session(engine) as session:
        versions = list({r.agent_version for r in session.exec(select(Run)).all()})
    board = []
    for v in versions:
        sc = generate_scorecard(v)
        board.append({
            "agent_version": v,
            "overall_score": sc.overall_score,
            "safety_status": sc.safety_status,
            "critical_guardrail_failures": sc.critical_guardrail_failures,
        })
    board.sort(key=lambda x: (x["overall_score"], x["safety_status"] == "PRODUCTION_READY"), reverse=True)
    return board


