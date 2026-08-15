"""
Three-Tier Error Taxonomy & Execution Result Contracts.
Explicitly distinguishes:
  1. Expected Business Outcomes (valid domain results like MEMBER_NOT_FOUND, not a crash)
  2. Recoverable Runtime Conditions (transient loading/interstitials, safely mitigated)
  3. Hard Failures & Stuck States (action roadblock, policy violations, diagnostic crashes)
"""
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field
from app.core.models import OutcomeType


class ErrorCategory(str):
    BUSINESS_OUTCOME = "BUSINESS_OUTCOME"
    RECOVERABLE = "RECOVERABLE"
    ESCALATE_HITL = "ESCALATE_HITL"
    HARD_FAILURE = "HARD_FAILURE"
    POLICY_VIOLATION = "POLICY_VIOLATION"


class StepExecutionRecord(BaseModel):
    step_id: str
    action: str
    target_description: Optional[str] = None
    matched_strategy: Optional[str] = None
    strategy_confidence: Optional[float] = None
    duration_ms: float = 0.0
    status: str = "SUCCESS"
    extracted_data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None


class DiagnosticContext(BaseModel):
    step_id: Optional[str] = None
    step_index: Optional[int] = None
    current_url: Optional[str] = None
    active_frame: Optional[str] = None
    expected: Optional[str] = None
    observed: Optional[str] = None
    screenshot_path: Optional[str] = None
    dom_snapshot_path: Optional[str] = None
    candidate_locators_tried: List[Dict[str, Any]] = Field(default_factory=list)


class ReplayResult(BaseModel):
    run_id: str
    capability_id: str
    version: str
    session_id: str
    status: OutcomeType
    outcome_code: Optional[str] = None
    message: str = "Execution completed"
    outputs: Dict[str, Any] = Field(default_factory=dict)
    steps_executed: int = 0
    duration_ms: float = 0.0
    step_trace: List[StepExecutionRecord] = Field(default_factory=list)
    error: Optional[DiagnosticContext] = None
    human_interventions: List[Dict[str, Any]] = Field(default_factory=list)
