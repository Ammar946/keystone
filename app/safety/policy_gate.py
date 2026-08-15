"""
Pre-Action Policy Gate.
Enforces domain allowlists, action verb constraints, and contextual risk classification
BEFORE any operation reaches the Surface Adapter.
"""
from typing import Dict, Any, Optional
from urllib.parse import urlparse
import re
from app.core.models import SafetyPolicy, RiskLevel, ActionType, Step


class PolicyViolationError(Exception):
    def __init__(self, message: str, rule: str, details: Dict[str, Any]):
        super().__init__(message)
        self.rule = rule
        self.details = details


class PolicyGate:
    """Pre-action evaluation engine ensuring safety guardrails are respected."""

    def __init__(self, policy: Optional[SafetyPolicy] = None):
        self.policy = policy or SafetyPolicy()

    def check_url(self, current_url: str) -> bool:
        """Validate whether the destination or current URL is permitted."""
        if not current_url:
            return True
        parsed = urlparse(current_url)
        netloc = parsed.netloc or parsed.path.split("/")[0]

        # Domain whitelist check
        allowed_domains = self.policy.allowed_routes # or allowed_domains in TargetEntryPoint
        # Default local safe sandbox domains
        safe_hosts = ["localhost", "127.0.0.1", "0.0.0.0"]
        host = netloc.split(":")[0]

        if host not in safe_hosts:
            raise PolicyViolationError(
                f"Domain '{netloc}' is not in allowed domain whitelist.",
                rule="DOMAIN_ALLOWLIST",
                details={"url": current_url, "host": host},
            )
        return True

    def evaluate_step(
        self,
        step: Step,
        current_url: str,
        human_approved: bool = False,
    ) -> Dict[str, Any]:
        """
        Pre-action gate: Evaluates (action, target, risk_level, url).
        Returns decision status: 'ALLOW', 'BLOCK', or 'REQUIRE_HITL'.
        """
        # 1. Check URL
        self.check_url(current_url)

        # 2. Check Action Verb
        action_verb = step.action.value if isinstance(step.action, ActionType) else str(step.action)
        if action_verb not in self.policy.allowed_actions:
            raise PolicyViolationError(
                f"Action '{action_verb}' is not in the allowed action policy {self.policy.allowed_actions}.",
                rule="ACTION_ALLOWLIST",
                details={"action": action_verb, "step_id": step.id},
            )

        # 3. Contextual Risk Analysis
        target_desc = (step.target.description or "") if step.target else ""
        step_desc = (step.description or "")
        combined_text = f"{action_verb} {target_desc} {step_desc}".lower()

        # Check explicit risk_level or suspicious irreversible keywords
        is_high_risk = step.risk_level in [RiskLevel.HIGH_RISK, RiskLevel.IRREVERSIBLE]
        risky_keywords = ["authorize", "delete", "destroy", "wire_transfer", "freeze", "provision", "bind account"]
        
        if any(kw in combined_text for kw in risky_keywords):
            is_high_risk = True

        if is_high_risk:
            if not human_approved and self.policy.requires_confirmation_on_risk:
                return {
                    "decision": "REQUIRE_HITL",
                    "reason": f"Step '{step.id}' contains high-risk/irreversible action ('{step_desc or target_desc}'). Requires human intervention.",
                    "risk_level": RiskLevel.HIGH_RISK.value,
                }

        return {"decision": "ALLOW", "risk_level": step.risk_level.value}
