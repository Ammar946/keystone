"""
Human-in-the-Loop (HITL) Escalation Manager.
Manages same-session live control transfer between Automation and Human Operator.
Enforces the explicit ControlOwner state machine:
  RUNNING_AUTOMATION -> AWAITING_HUMAN -> HUMAN_CONTROL -> RESUMING -> RUNNING_AUTOMATION.
"""
from typing import Dict, Any, Optional, List
import time
import os
import json
from app.core.surface_adapter import ControlOwner, ExecutionState, SurfaceAdapter
from app.core.models import Step, RiskLevel
from app.core.error_taxonomy import ReplayResult


class HITLEscalationManager:
    """Manages same-session live escalation, context packaging, and control handback."""

    def __init__(self, surface: SurfaceAdapter, evidence_dir: str = "evidence/replay-hitl"):
        self.surface = surface
        self.evidence_dir = evidence_dir
        self.control_owner: ControlOwner = ControlOwner.AUTOMATION
        self.execution_state: ExecutionState = ExecutionState.RUNNING_AUTOMATION
        self.human_actions_log: List[Dict[str, Any]] = []
        os.makedirs(self.evidence_dir, exist_ok=True)

    async def raise_intervention_request(
        self,
        capability_id: str,
        step: Step,
        step_index: int,
        reason: str,
    ) -> Dict[str, Any]:
        """
        Pauses automation, captures live diagnostic context, and cedes control to human.
        """
        self.control_owner = ControlOwner.HUMAN
        self.execution_state = ExecutionState.AWAITING_HUMAN
        session_id = await self.surface.get_session_id()

        # Capture screenshot for operator package
        screenshot_filename = f"intervention_{session_id}_step_{step_index}.png"
        screenshot_path = os.path.join(self.evidence_dir, screenshot_filename)
        
        try:
            screenshot_bytes = await self.surface.capture_screenshot(mask_sensitive=True)
            if screenshot_bytes:
                with open(screenshot_path, "wb") as f:
                    f.write(screenshot_bytes)
        except Exception:
            screenshot_path = None

        intervention_pkg = {
            "session_id": session_id,
            "capability_id": capability_id,
            "step_id": step.id,
            "step_index": step_index,
            "reason": reason,
            "risk_level": step.risk_level.value if isinstance(step.risk_level, RiskLevel) else str(step.risk_level),
            "timestamp": time.time(),
            "screenshot_path": screenshot_path,
            "current_owner": self.control_owner.value,
            "status": self.execution_state.value,
        }

        # Write intervention package to evidence
        pkg_path = os.path.join(self.evidence_dir, "intervention.json")
        with open(pkg_path, "w") as f:
            json.dump(intervention_pkg, f, indent=2)

        return intervention_pkg

    async def complete_human_takeover(
        self,
        operator_id: str = "operator_admin_01",
        action_taken: str = "Manual review and authorized creation",
        resume_signal: bool = True,
    ) -> bool:
        """
        Records the manual action taken on the live session, transitions ownership, and resumes.
        """
        self.execution_state = ExecutionState.HUMAN_CONTROL
        session_id = await self.surface.get_session_id()

        action_entry = {
            "session_id": session_id,
            "operator_id": operator_id,
            "action_taken": action_taken,
            "timestamp": time.time(),
            "status": "APPROVED_AND_RESUMED" if resume_signal else "ABORTED",
        }
        self.human_actions_log.append(action_entry)

        # Append to human_actions.jsonl
        log_path = os.path.join(self.evidence_dir, "human_actions.jsonl")
        with open(log_path, "a") as f:
            f.write(json.dumps(action_entry) + "\n")

        if resume_signal:
            self.execution_state = ExecutionState.RESUMING
            self.control_owner = ControlOwner.AUTOMATION
            return True
        else:
            self.execution_state = ExecutionState.ABORTED
            return False

    def confirm_resumption_complete(self) -> None:
        """Called after postcondition verification to fully transition back to RUNNING_AUTOMATION."""
        self.execution_state = ExecutionState.RUNNING_AUTOMATION
        self.control_owner = ControlOwner.AUTOMATION

    def mark_completed(self) -> None:
        """Called when capability execution successfully completes."""
        self.execution_state = ExecutionState.COMPLETED
