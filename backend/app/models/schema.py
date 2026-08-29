from typing import List, Optional, Dict, Any
from datetime import datetime
from sqlmodel import SQLModel, Field, Column, JSON
from pydantic import BaseModel

# 3.1 Tool Schema
class ToolDef(SQLModel, table=True):
    __tablename__ = "tool"
    id: Optional[int] = Field(default=None, primary_key=True)
    agent_domain: str
    name: str
    description: str
    parameters: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    irreversibility: str  # none | low | high | critical

# 3.2 Scenario Schema
class Scenario(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    scenario_id: str = Field(index=True, unique=True)
    agent_domain: str
    category: str
    target_tool: Optional[str] = None
    pressure_technique: Optional[str] = None
    turns: List[Dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    scripted_responses: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    safe_behavior: str
    unsafe_behavior: str
    severity: str  # low | medium | high | critical

# 3.3 Trace Schema
class Run(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(index=True, unique=True)
    scenario_id: str
    agent_version: str
    started_at: datetime
    steps: List[Dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))

# 3.4 Verdict Schema
class Verdict(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(index=True, unique=True)
    scenario_id: str
    outcome: str  # PASS | FAIL
    failure_category: Optional[str] = None
    severity: str  # low | medium | high | critical
    evidence_step: Optional[int] = None
    expected_behavior: Optional[str] = None
    actual_behavior: Optional[str] = None
    explanation: Optional[str] = None

# 3.5 Scorecard Schema (Output model)
class Regression(BaseModel):
    scenario_id: str
    previous: str
    current: str

class GuardrailMetric(BaseModel):
    tool: str
    pass_rate: float
    status: str = "PASSED"

class Scorecard(BaseModel):
    agent_version: str
    overall_score: int
    safety_status: str  # UNSAFE | NEEDS_REVIEW | PRODUCTION_READY
    critical_guardrail_failures: int
    sub_scores: Dict[str, int]
    # Axes with zero evaluated verdicts. The UI renders these as "No data" rather
    # than a fabricated 100%, and they are excluded from the overall score.
    untested_axes: List[str] = []
    category_radar: Dict[str, int]
    guardrail_table: List[GuardrailMetric]
    regressions: List[Regression]
    # Count of runs that could not be judged (no API key / judge error). A suite
    # with un-evaluated runs can never be certified PRODUCTION_READY.
    not_evaluated_count: int = 0
    scoring_rationale: Optional[str] = None

# Agent Version tracking
class AgentVersion(SQLModel, table=True):
    __tablename__ = "agent_version"
    id: Optional[int] = Field(default=None, primary_key=True)
    version_name: str = Field(index=True, unique=True)
    domain: str
    system_prompt: str

# Feature 3: Threat Library — reusable saved attacks (typically captured from a
# failing run) that can be re-run as a regression suite against any agent version.
class LibraryEntry(SQLModel, table=True):
    __tablename__ = "library_entry"
    id: Optional[int] = Field(default=None, primary_key=True)
    entry_id: str = Field(index=True, unique=True)
    title: str
    agent_domain: str
    category: str
    severity: str  # low | medium | high | critical
    target_tool: Optional[str] = None
    pressure_technique: Optional[str] = None
    turns: List[Dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    scripted_responses: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    safe_behavior: str = ""
    unsafe_behavior: str = ""
    source_agent_version: Optional[str] = None
    source_scenario_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
