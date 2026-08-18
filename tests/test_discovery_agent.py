"""
Unit & Integration Tests for Goal-Driven LLM Discovery Agent.
Validates:
  1. LLMActionDecision schema bounds and validation.
  2. Mocked live OpenAI API client invocation (asserting API call and live_llm_api mode).
  3. Complete Observe-Decide-Validate-Act discovery loop synthesizing DiscoveryTranscript.
"""
import pytest
import os
import json
from unittest.mock import AsyncMock, MagicMock
from app.agent.discovery_agent import DiscoveryAgent, LLMActionDecision
from app.core.models import ActionType


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
async def test_discovery_agent_calls_openai_api(tmp_path):
    """
    Verify that when configured with API credentials / mock client,
    DiscoveryAgent genuinely invokes the OpenAI chat completions API.
    """
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_message = MagicMock()
    
    mock_message.content = json.dumps({
        "thought": "API test step: type member ID",
        "action": "type",
        "target_description": "Member ID Input",
        "target_selector": "textbox[name='Member ID / Account #']",
        "selector_strategy": "accessibility",
        "value": "10042",
        "is_finished": False,
    })
    mock_choice.message = mock_message
    mock_response.choices = [mock_choice]
    
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    evidence_dir = str(tmp_path / "mock_api_evidence")
    agent = DiscoveryAgent(
        evidence_dir=evidence_dir,
        api_key="sk-mock-key-test-12345",
        client=mock_client,
    )

    decision = await agent._decide_action_with_llm(
        goal="Search member 10042",
        state=MagicMock(url_or_window="http://localhost:8080/console/members", title="Apex CoreBank", interactive_elements=[], text_content=""),
        step_history=[],
        sample_inputs={"member_id": "10042"},
        step_index=1,
    )

    mock_client.chat.completions.create.assert_called_once()
    assert decision.action == "type"
    assert decision.value == "10042"


@pytest.mark.asyncio
async def test_discovery_agent_observe_decide_act_loop(tmp_path):
    """
    Test complete discovery loop against mock banking target:
    Observe page -> LLM decision -> Safety validation -> Execution -> Transcript -> Artifact generation.
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
    assert artifact.provenance is not None
    assert artifact.provenance.model == "gpt-4o"
    assert os.path.exists(os.path.join(evidence_dir, "run.json"))
    assert os.path.exists(os.path.join(evidence_dir, "actions.jsonl"))
    assert os.path.exists(os.path.join(evidence_dir, "compiled_capability.json"))

    with open(os.path.join(evidence_dir, "run.json"), "r") as f:
        run_data = json.load(f)
    assert run_data["status"] == "SUCCESS"
    assert run_data["steps_recorded"] >= 3
    assert run_data["provider"] == "openai"
