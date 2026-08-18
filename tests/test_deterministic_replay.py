"""
Integration Tests for Deterministic Replay (Zero-LLM Execution).
Covers:
  - Happy path member balance extraction
  - Expected business outcome (Record Not Found)
  - Transient interstitial runtime recovery
  - Broken primary locator fallback resilience
  - Mechanically verifiable Zero-LLM isolation property
  - Complete End-to-End Golden Path (Discover -> Compile -> Replay -> HITL -> Resumption)
"""
import pytest
import asyncio
import threading
import time
import json
import uvicorn
from unittest.mock import patch
from app.target_app.server import app as fastapi_app
from app.core.models import (
    CapabilityArtifact,
    OutcomeType,
    LocatorCandidate,
    Step,
    TargetSpec,
)
from app.engine.replay_engine import DeterministicReplayEngine
from app.agent.discovery_agent import DiscoveryAgent


@pytest.fixture(scope="session", autouse=True)
def run_target_server():
    """Start local mock banking server for test session if not already running."""
    import socket
    sock = socket.socket(socket.AF_SOCKET if hasattr(socket, "AF_SOCKET") else socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('127.0.0.1', 8080))
    sock.close()
    
    server = None
    if result != 0:
        # Port is free, start server
        config = uvicorn.Config(fastapi_app, host="127.0.0.1", port=8080, log_level="error")
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        time.sleep(1.0)
    yield
    if server:
        server.should_exit = True


@pytest.mark.asyncio
async def test_deterministic_replay_happy_path():
    """Verify zero-LLM deterministic replay extracts correct typed outputs."""
    with open("artifacts/get_member_balance.json", "r") as f:
        artifact = CapabilityArtifact.model_validate(json.load(f))

    engine = DeterministicReplayEngine()
    result = await engine.replay(
        artifact=artifact,
        inputs={"member_id": "10042"},
        headless=True,
    )

    assert result.status == OutcomeType.SUCCESS
    assert result.outputs["member_name"] == "Jane Doe"
    assert result.outputs["account_status"] == "ACTIVE"
    assert result.outputs["savings_balance"] == 12450.75
    assert result.outputs["checking_balance"] == 3210.50
    assert result.steps_executed == 3


@pytest.mark.asyncio
async def test_deterministic_replay_business_outcome_not_found():
    """Verify non-existent member returns structured BUSINESS_OUTCOME rather than crashing."""
    with open("artifacts/get_member_balance.json", "r") as f:
        artifact = CapabilityArtifact.model_validate(json.load(f))

    engine = DeterministicReplayEngine()
    result = await engine.replay(
        artifact=artifact,
        inputs={"member_id": "99999"},
        headless=True,
    )

    assert result.status == OutcomeType.BUSINESS_OUTCOME
    assert result.outcome_code == "MEMBER_NOT_FOUND"
    assert "Record does not exist" in result.message or "not found" in result.message.lower()
    assert result.steps_executed == 2


@pytest.mark.asyncio
async def test_deterministic_replay_transient_interstitial_recovery():
    """Verify engine recovers from transient popup notices on idempotent actions."""
    with open("artifacts/get_member_balance.json", "r") as f:
        artifact = CapabilityArtifact.model_validate(json.load(f))

    # Target route with interstitial modal query param
    artifact.entry_point.route = "/console/members?interstitial=true"

    engine = DeterministicReplayEngine()
    result = await engine.replay(
        artifact=artifact,
        inputs={"member_id": "20088"},
        headless=True,
    )

    assert result.status == OutcomeType.SUCCESS
    assert result.outputs["member_name"] == "Robert Martinez"
    assert result.outputs["savings_balance"] == 54800.00


@pytest.mark.asyncio
async def test_broken_primary_locator_falls_back_to_xpath():
    """
    Deliberately broken locator resilience test:
    Intentionally corrupt primary Accessibility and CSS locators to non-existent values.
    Verify that the resolver falls back to structural XPath and execution succeeds.
    """
    with open("artifacts/get_member_balance.json", "r") as f:
        artifact = CapabilityArtifact.model_validate(json.load(f))

    # Inject broken primary locators on step 1
    artifact.steps[0].target.locators = [
        LocatorCandidate(strategy="accessibility", value="textbox[name='NonExistentCorruptedField']", priority=1, confidence=0.99),
        LocatorCandidate(strategy="css_scoped", value="#corrupted_bogus_id", priority=2, confidence=0.95),
        LocatorCandidate(strategy="xpath_structural", value="//tr[td[contains(.,'Member ID')]]/td/input", priority=3, confidence=0.75),
    ]

    engine = DeterministicReplayEngine()
    result = await engine.replay(
        artifact=artifact,
        inputs={"member_id": "10042"},
        headless=True,
    )

    assert result.status == OutcomeType.SUCCESS
    # Step 1 should have fallen back to xpath_structural
    assert result.step_trace[0].matched_strategy == "xpath_structural"
    assert result.step_trace[0].strategy_confidence == 0.75
    assert result.outputs["member_name"] == "Jane Doe"


@pytest.mark.asyncio
async def test_replay_engine_zero_llm_isolation():
    """
    Verify that DeterministicReplayEngine executes with ZERO LLM invocations.
    Patches openai client to raise an exception if invoked during replay.
    """
    with open("artifacts/get_member_balance.json", "r") as f:
        artifact = CapabilityArtifact.model_validate(json.load(f))

    with patch("openai.AsyncOpenAI", side_effect=RuntimeError("ReplayEngine invoked LLM! Zero-LLM violation")):
        engine = DeterministicReplayEngine()
        result = await engine.replay(
            artifact=artifact,
            inputs={"member_id": "10042"},
            headless=True,
        )
        assert result.status == OutcomeType.SUCCESS


@pytest.mark.asyncio
async def test_end_to_end_discover_compile_replay_hitl(tmp_path):
    """
    Golden Path End-to-End Integration Test:
    1. LLM Discovery Agent explores live member search page and generates DiscoveryTranscript.
    2. ArtifactCompiler compiles transcript into a validated CapabilityArtifact with provenance.
    3. ReplayEngine replays compiled artifact deterministically (Zero-LLM).
    4. Sub-account creation encounters high-risk authorization step -> triggers same-session HITL.
    5. Operator takes over live page -> authorizes -> resumes automation -> confirms ledger booking.
    """
    disc_dir = str(tmp_path / "e2e_discovery")
    replay_dir = str(tmp_path / "e2e_replay")
    
    # 1. Discover
    disc_agent = DiscoveryAgent(evidence_dir=disc_dir)
    discovered_artifact = await disc_agent.discover_capability(
        goal="Look up member 10042 and read savings balance",
        entry_point="http://localhost:8080/console/members",
        sample_inputs={"member_id": "10042"},
        headless=True,
    )
    assert discovered_artifact.capability_id == "corebank.member.get_balance"
    assert discovered_artifact.provenance is not None

    # 2. Replay Discovered Artifact (Zero-LLM)
    replay_engine = DeterministicReplayEngine()
    replay_res = await replay_engine.replay(
        artifact=discovered_artifact,
        inputs={"member_id": "10042"},
        headless=True,
        evidence_dir=replay_dir,
    )
    assert replay_res.status == OutcomeType.SUCCESS
    assert replay_res.outputs["member_name"] == "Jane Doe"
    assert replay_res.outputs["savings_balance"] == 12450.75

    # 3. Replay with HITL Escalation & Resumption on sub-account creation
    with open("artifacts/open_sub_account.json", "r") as f:
        sub_artifact = CapabilityArtifact.model_validate(json.load(f))

    hitl_res = await replay_engine.replay(
        artifact=sub_artifact,
        inputs={"member_id": "10042", "account_type": "Money Market", "deposit_amount": 500.00},
        headless=True,
        enable_hitl=True,
        auto_approve_hitl=True,
        evidence_dir=str(tmp_path / "e2e_hitl"),
    )
    assert hitl_res.status == OutcomeType.SUCCESS
    assert len(hitl_res.human_interventions) == 1
    assert hitl_res.outputs.get("new_account_number", "").startswith("00910042-")
