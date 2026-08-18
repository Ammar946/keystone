"""
Integration Tests for Same-Session Human-in-the-Loop (HITL) Escalation.
Validates:
  1. HITLEscalationManager state transitions on the same live session.
  2. End-to-end DeterministicReplayEngine escalation -> takeover -> resumption -> completion.
"""
import pytest
import os
import json
from app.core.models import CapabilityArtifact, OutcomeType
from app.core.surface_adapter import ControlOwner, ExecutionState
from app.adapters.playwright_adapter import PlaywrightSurfaceAdapter
from app.hitl.escalation_manager import HITLEscalationManager
from app.engine.replay_engine import DeterministicReplayEngine


@pytest.mark.asyncio
async def test_same_session_hitl_escalation_manager(tmp_path):
    """
    Verify complete same-session control transfer via HITLEscalationManager:
    1. Automation operates on session_id = 'sess_test_101'
    2. Roadblock/risk triggers intervention package
    3. Control transitions to HUMAN
    4. Operator acts on the SAME live session
    5. Control transfers back to AUTOMATION and completes successfully
    """
    evidence_dir = str(tmp_path / "hitl_evidence")
    session_id = "sess_test_hitl_999"

    with open("artifacts/open_sub_account.json", "r") as f:
        artifact = CapabilityArtifact.model_validate(json.load(f))

    surface = PlaywrightSurfaceAdapter()
    await surface.initialize(session_id=session_id, entry_point="http://localhost:8080/console/accounts/open", headless=True)
    escalation_mgr = HITLEscalationManager(surface=surface, evidence_dir=evidence_dir)

    try:
        # 1. Fill input fields via automation
        elem1 = await surface.resolve_target(artifact.steps[0].target.model_dump())
        await surface.type_text(elem1, "10042")
        elem2 = await surface.resolve_target(artifact.steps[1].target.model_dump())
        await surface.select_option(elem2, "Certificate of Deposit")
        elem3 = await surface.resolve_target(artifact.steps[2].target.model_dump())
        await surface.type_text(elem3, "1500.00")
        elem4 = await surface.resolve_target(artifact.steps[3].target.model_dump())
        await surface.click(elem4)

        # 2. Trigger HITL Escalation on Step 5 (Authorize Creation)
        intervention_pkg = await escalation_mgr.raise_intervention_request(
            capability_id=artifact.capability_id,
            step=artifact.steps[4],
            step_index=5,
            reason="High-risk irreversible sub-account creation",
        )

        assert escalation_mgr.control_owner == ControlOwner.HUMAN
        assert escalation_mgr.execution_state == ExecutionState.AWAITING_HUMAN
        assert intervention_pkg["session_id"] == session_id
        assert os.path.exists(os.path.join(evidence_dir, "intervention.json"))

        # 3. Simulate Operator Taking Over Live Session
        frame_elem = await surface.resolve_target(artifact.steps[4].target.model_dump(), frame_context="dialog_frame")
        await surface.click(frame_elem)

        resumed = await escalation_mgr.complete_human_takeover(
            operator_id="operator_test_01",
            action_taken="Approved CD account opening",
            resume_signal=True,
        )

        assert resumed is True
        assert escalation_mgr.control_owner == ControlOwner.AUTOMATION
        assert escalation_mgr.execution_state == ExecutionState.RESUMING
        assert os.path.exists(os.path.join(evidence_dir, "human_actions.jsonl"))

        escalation_mgr.confirm_resumption_complete()
        assert escalation_mgr.execution_state == ExecutionState.RUNNING_AUTOMATION

        # 4. Automation resumes on same live session to extract confirmation
        acc_elem = await surface.resolve_target({"locators": [{"strategy": "xpath_structural", "value": "//strong[@id='lbl_new_account_number']"}]})
        new_account_number = await surface.read_text(acc_elem)
        assert new_account_number.startswith("00910042-")

    finally:
        await surface.close()


@pytest.mark.asyncio
async def test_replay_engine_end_to_end_hitl_takeover(tmp_path):
    """
    Verify that DeterministicReplayEngine seamlessly handles HITL takeover
    and resumes execution on the same live session to status SUCCESS.
    """
    evidence_dir = str(tmp_path / "replay_hitl_evidence")
    with open("artifacts/open_sub_account.json", "r") as f:
        artifact = CapabilityArtifact.model_validate(json.load(f))

    engine = DeterministicReplayEngine()
    result = await engine.replay(
        artifact=artifact,
        inputs={"member_id": "10042", "account_type": "Money Market", "deposit_amount": 500.00},
        headless=True,
        enable_hitl=True,
        auto_approve_hitl=True,
        evidence_dir=evidence_dir,
    )

    assert result.status == OutcomeType.SUCCESS
    assert len(result.human_interventions) == 1
    assert result.outputs.get("new_account_number", "").startswith("00910042-")
    assert result.outputs.get("confirmed_deposit") == 500.00
