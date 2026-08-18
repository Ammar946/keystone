"""
Unit & Integration Tests for Goal-Driven LLM Discovery Agent.
Validates the Observe-Decide-Validate-Act loop and structured decision schema.
"""
import pytest
import os
import json
from unittest.mock import AsyncMock, MagicMock, patch
from app.agent.discovery_agent import DiscoveryAgent, LLMActionDecision
from app.adapters.playwright_adapter import PlaywrightSurfaceAdapter


@pytest.mark.asyncio
async def test_discovery_agent_decision_schema_validation():
    """Verify LLMActionDecision parsing and schema bounds."""
    decision_json = {
        "thought": "Observed Member ID search textbox. Need to type target member ID.",
        "action": "type",
        "target_description": "Member ID Input Field",
        "target_selector": "textbox[name='Member ID / Account #']",
        "selector_strategy": "accessibility",
        "value": "10042",
        "is_finished": False,
    }
    decision = LLMActionDecision.model_validate(decision_json)
    assert decision.action == "type"
    assert decision.target_selector == "textbox[name='Member ID / Account #']"
    assert decision.value == "10042"
    assert decision.is_finished is False


@pytest.mark.asyncio
async def test_discovery_agent_observe_decide_act_loop(tmp_path):
    """
    Test complete discovery loop against mock banking target:
    Observe page -> LLM decision -> Safety validation -> Execution -> Artifact generation.
    """
    evidence_dir = str(tmp_path / "discovery_evidence")
    agent = DiscoveryAgent(evidence_dir=evidence_dir)

    artifact = await agent.discover_capability(
        goal="Look up member 10042 and read savings balance",
        entry_point="http://localhost:8080/console/members",
        sample_inputs={"member_id": "10042"},
        headless=True,
    )

    assert artifact.capability_id == "corebank.member.get_balance"
    assert os.path.exists(os.path.join(evidence_dir, "run.json"))
    assert os.path.exists(os.path.join(evidence_dir, "actions.jsonl"))
    assert os.path.exists(os.path.join(evidence_dir, "compiled_capability.json"))

    with open(os.path.join(evidence_dir, "run.json"), "r") as f:
        run_data = json.load(f)
    assert run_data["status"] == "SUCCESS"
    assert run_data["steps_recorded"] >= 3
