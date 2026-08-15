"""
Unit Tests for Capability Artifact Schemas and Validation.
"""
import pytest
import json
from pydantic import ValidationError
from app.core.models import (
    CapabilityArtifact,
    Step,
    TargetSpec,
    LocatorCandidate,
    ActionType,
    RiskLevel,
    CapabilityStatus,
)


def test_valid_capability_artifact_parsing():
    """Verify that valid capability artifact JSON parses correctly into Pydantic models."""
    with open("artifacts/get_member_balance.json", "r") as f:
        data = json.load(f)
    
    artifact = CapabilityArtifact.model_validate(data)
    assert artifact.capability_id == "corebank.member.get_balance"
    assert artifact.status == CapabilityStatus.APPROVED
    assert len(artifact.steps) == 3
    assert artifact.steps[0].action == ActionType.TYPE
    assert artifact.steps[0].risk_level == RiskLevel.READ_ONLY
    assert len(artifact.steps[0].target.locators) == 3


def test_invalid_artifact_schema_rejection():
    """Verify that malformed schemas raise ValidationError."""
    invalid_data = {
        "schema_version": "1.0.0",
        "capability_id": "corebank.invalid",
        # Missing required name, description, steps
    }
    with pytest.raises(ValidationError):
        CapabilityArtifact.model_validate(invalid_data)


def test_locator_candidate_confidence_bounds():
    """Ensure locator confidence is bounded between 0.0 and 1.0."""
    valid_candidate = LocatorCandidate(strategy="accessibility", value="button[name='Save']", confidence=0.95)
    assert valid_candidate.confidence == 0.95

    with pytest.raises(ValidationError):
        LocatorCandidate(strategy="accessibility", value="button[name='Save']", confidence=1.5)
