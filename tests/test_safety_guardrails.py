"""
Unit Tests for Safety Policy Gate, Risk Gates, and PII Redaction.
"""
import pytest
from app.safety.pii_redactor import PIIRedactor
from app.safety.policy_gate import PolicyGate, PolicyViolationError
from app.core.models import SafetyPolicy, Step, ActionType, RiskLevel, TargetSpec


def test_pii_redactor_text_masking():
    """Verify regex redactor masks SSN, Card PAN, and API secrets."""
    sample_text = "Member SSN is 123-45-6789 and card is 4532-1234-5678-9012 with api_key='sk_live_998877665544'"
    redacted = PIIRedactor.redact_text(sample_text)
    
    assert "123-45-6789" not in redacted
    assert "***-**-6789" in redacted
    assert "4532-1234-5678-9012" not in redacted
    assert "****-****-****-9012" in redacted
    assert "sk_live_998877665544" not in redacted


def test_pii_redactor_structured_dict():
    """Verify recursive dictionary redaction."""
    data = {
        "user": {"name": "Alice", "ssn": "987-65-4321"},
        "auth": {"password": "secretPassword123", "token": "Bearer abcdef1234567890"},
    }
    redacted = PIIRedactor.redact_structured_data(data)
    
    assert redacted["user"]["ssn"] == "***-**-4321"
    assert redacted["auth"]["password"] == "[REDACTED_SECRET]"


def test_policy_gate_domain_allowlist():
    """Verify PolicyGate rejects disallowed untrusted domains."""
    gate = PolicyGate(SafetyPolicy(allowed_routes=["^/console/.*$"]))
    
    # Safe localhost domain passes
    assert gate.check_url("http://localhost:8080/console/members") is True
    
    # Untrusted domain raises PolicyViolationError
    with pytest.raises(PolicyViolationError) as exc_info:
        gate.check_url("http://malicious-external-bank.com/steal-data")
    assert exc_info.value.rule == "DOMAIN_ALLOWLIST"


def test_policy_gate_action_allowlist():
    """Verify PolicyGate rejects unauthorized action verbs."""
    gate = PolicyGate(SafetyPolicy(allowed_actions=["click", "type"]))
    
    step_invalid = Step(
        id="step_hack",
        action=ActionType.CUSTOM,
        description="Run arbitrary script",
    )
    with pytest.raises(PolicyViolationError) as exc_info:
        gate.evaluate_step(step_invalid, "http://localhost:8080/console")
    assert exc_info.value.rule == "ACTION_ALLOWLIST"


def test_policy_gate_high_risk_escalation():
    """Verify high-risk irreversible actions trigger REQUIRE_HITL."""
    gate = PolicyGate(SafetyPolicy(requires_confirmation_on_risk=True))
    
    step_risky = Step(
        id="step_transfer",
        action=ActionType.CLICK,
        risk_level=RiskLevel.HIGH_RISK,
        description="Authorize irreversible wire transfer",
    )
    decision = gate.evaluate_step(step_risky, "http://localhost:8080/console")
    assert decision["decision"] == "REQUIRE_HITL"
    assert decision["risk_level"] == "HIGH_RISK"
