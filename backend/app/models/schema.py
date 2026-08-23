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
    category_radar: Dict[str, int]
    guardrail_table: List[GuardrailMetric]
    regressions: List[Regression]
    scoring_rationale: Optional[str] = None

# Agent Version tracking
class AgentVersion(SQLModel, table=True):
    __tablename__ = "agent_version"
    id: Optional[int] = Field(default=None, primary_key=True)
    version_name: str = Field(index=True, unique=True)
    domain: str
    system_prompt: str
