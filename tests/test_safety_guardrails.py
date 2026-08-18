"""
Unit Tests for Safety Policy Gate and PII Redaction Pipeline.
Covers:
  - Text and structured dictionary PII/secret redaction
  - Explicit Route & Domain allowlist validation (ALLOW, DENY, TENANT_OVERRIDE)
  - Action verb allowlist enforcement
  - High-risk contextual safety classification
"""
import pytest
from app.safety.pii_redactor import PIIRedactor
from app.safety.policy_gate import PolicyGate, PolicyViolationError
from app.core.models import SafetyPolicy, RiskLevel, ActionType, Step


def test_pii_redactor_text_masking():
    """Verify SSNs, Credit Cards, and Auth Tokens are masked in unstructured text."""
    raw_text = "Member John Doe SSN: 123-45-6789 with Card: 4532-1234-5678-9012 and Token: bearer eyJhbGciOi"
    masked = PIIRedactor.redact_text(raw_text)
    
    assert "123-45-6789" not in masked
    assert "4532-1234-5678-9012" not in masked
    assert "eyJhbGciOi" not in masked
    assert "***-**-6789" in masked
    assert "****-****-****-9012" in masked


def test_pii_redactor_structured_dict():
    """Verify recursive redaction in nested dictionary payloads."""
    payload = {
        "user": {
            "name": "Jane Doe",
            "password": "SuperSecretPassword123!",
            "ssn": "987-65-4321",
        },
        "logs": ["API call with auth_token=secret_abc123"],
    }
    redacted = PIIRedactor.redact_structured_data(payload)
    assert redacted["user"]["password"] == "[REDACTED_SECRET]"
    assert redacted["user"]["ssn"] == "***-**-4321"
    assert "secret_abc123" not in redacted["logs"][0]


def test_policy_gate_domain_allowlist():
    """Verify PolicyGate rejects disallowed target host domains."""
    gate = PolicyGate(allowed_domains=["localhost:8080", "127.0.0.1:8080"])
    
    # Safe localhost domain
    assert gate.check_url("http://localhost:8080/console/members") is True
    
    # Forbidden external domain
    with pytest.raises(PolicyViolationError) as exc_info:
        gate.check_url("https://malicious-banking-phish.com/console/members")
    assert exc_info.value.rule == "DOMAIN_ALLOWLIST"


def test_policy_gate_route_allowlist():
    """Verify PolicyGate rejects unauthorized routes outside the declared whitelist."""
    gate = PolicyGate(
        allowed_domains=["localhost:8080"],
        allowed_routes=["^/console.*$"],
    )
    
    # Allowed route
    assert gate.check_url("http://localhost:8080/console/members") is True
    assert gate.check_url("http://localhost:8080/console") is True
    
    # Unauthorized administration route
    with pytest.raises(PolicyViolationError) as exc_info:
        gate.check_url("http://localhost:8080/admin/delete-all-records")
    assert exc_info.value.rule == "ROUTE_ALLOWLIST"


def test_policy_gate_tenant_override_domain():
    """Verify PolicyGate permits custom tenant domains when configured in allowed_domains."""
    gate = PolicyGate(
        allowed_domains=["localhost:8080", "core.banka.com", "bankb-core.net"],
        allowed_routes=["^/console.*$"],
    )
    
    # Custom tenant domain
    assert gate.check_url("https://core.banka.com/console/members") is True
    assert gate.check_url("https://bankb-core.net/console/accounts") is True
    
    # Unwhitelisted third party
    with pytest.raises(PolicyViolationError):
        gate.check_url("https://unregistered-tenant.com/console/members")


def test_policy_gate_action_allowlist():
    """Verify PolicyGate rejects unauthorized action verbs."""
    gate = PolicyGate(
        policy=SafetyPolicy(allowed_actions=["click", "type", "extract", "wait", "scroll"]),
        allowed_domains=["localhost:8080"],
    )

    step_invalid = Step(
        id="step_custom_exec",
        action=ActionType.CUSTOM,
        description="Run arbitrary script",
    )
    with pytest.raises(PolicyViolationError) as exc_info:
        gate.evaluate_step(step_invalid, "http://localhost:8080/console/members")
    assert exc_info.value.rule == "ACTION_ALLOWLIST"


def test_policy_gate_high_risk_escalation():
    """Verify high-risk irreversible actions trigger REQUIRE_HITL."""
    gate = PolicyGate(
        policy=SafetyPolicy(requires_confirmation_on_risk=True),
        allowed_domains=["localhost:8080"],
    )

    step_risky = Step(
        id="step_transfer",
        action=ActionType.CLICK,
        risk_level=RiskLevel.HIGH_RISK,
        description="Authorize irreversible wire transfer",
    )
    decision = gate.evaluate_step(step_risky, "http://localhost:8080/console/members")
    assert decision.decision == "REQUIRE_HITL"
    assert decision.allowed is False
