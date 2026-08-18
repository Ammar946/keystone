"""
Integration Tests for Deterministic Replay (Zero-LLM Execution).
Covers:
  - Happy path member balance extraction
  - Expected business outcome (Record Not Found)
  - Transient interstitial runtime recovery
"""
import pytest
import asyncio
import threading
import time
import json
import uvicorn
from app.target_app.server import app as fastapi_app
from app.core.models import CapabilityArtifact, OutcomeType
from app.engine.replay_engine import DeterministicReplayEngine


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
