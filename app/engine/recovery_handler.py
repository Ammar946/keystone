"""
Idempotency-Aware Bounded Runtime Recovery Handler.
Handles known transient conditions (modals, overlays, slow loading spinners)
with condition classification, policy-driven retry evaluation, and strict max_attempts enforcement.
"""
from typing import List, Optional, Dict, Any, Tuple
from app.core.models import Step, RecoveryRule, RiskLevel, RuntimeCondition
from app.core.surface_adapter import SurfaceAdapter, SurfaceState


class RecoveryHandler:
    """Bounded, safe recovery executor for transient runtime conditions."""

    def __init__(self):
        self.attempt_counts: Dict[str, int] = {}
        self.recovery_records: List[Dict[str, Any]] = []

    def classify_condition(
        self,
        observed_error: Exception,
        state: Optional[SurfaceState] = None,
    ) -> RuntimeCondition:
        """
        Explicit condition classifier mapping runtime errors/states to known transient conditions.
        """
        err_msg = str(observed_error).lower()
        if "intercepted" in err_msg or "overlay" in err_msg or "modal" in err_msg or "blocked" in err_msg:
            return RuntimeCondition.TRANSIENT_INTERSTITIAL
        elif "timeout" in err_msg or "waiting" in err_msg:
            return RuntimeCondition.LOADING_SPINNER
        elif "not ready" in err_msg or "detached" in err_msg:
            return RuntimeCondition.ELEMENT_NOT_READY
        return RuntimeCondition.UNKNOWN

    def can_retry_step(
        self,
        step: Step,
        condition: str,
        max_attempts: int = 1,
    ) -> Tuple[bool, str]:
        """
        Policy-driven retry evaluation:
        Checks idempotency, retryability, risk level, and attempt bounds.
        """
        if step.risk_level in [RiskLevel.HIGH_RISK, RiskLevel.IRREVERSIBLE]:
            return False, "HIGH_RISK_IRREVERSIBLE"
        if not step.idempotent:
            return False, "NON_IDEMPOTENT_ACTION"
        if not step.retryable:
            return False, "NOT_RETRYABLE"

        key = f"{step.id}:{condition}"
        current_attempts = self.attempt_counts.get(key, 0)
        if current_attempts >= max_attempts:
            return False, f"MAX_ATTEMPTS_EXCEEDED ({current_attempts}/{max_attempts})"

        return True, "IDEMPOTENT_RETRYABLE"

    async def try_recover(
        self,
        step: Step,
        surface: SurfaceAdapter,
        observed_error: Exception,
    ) -> bool:
        """
        Attempts bounded recovery if the condition is recognized and retry policy permits.
        """
        classified_condition = self.classify_condition(observed_error)
        
        if not step.recovery_rules:
            return False

        for rule in step.recovery_rules:
            if rule.condition == classified_condition.value or rule.condition == "TRANSIENT_INTERSTITIAL":
                key = f"{step.id}:{rule.condition}"
                current_attempts = self.attempt_counts.get(key, 0)
                
                # Check retry policy
                allowed, reason = self.can_retry_step(step, rule.condition, rule.max_attempts)
                if not allowed:
                    continue

                if rule.condition == "TRANSIENT_INTERSTITIAL" and rule.target:
                    try:
                        dismiss_elem = await surface.resolve_target(rule.target.model_dump(), timeout_ms=2000)
                        if dismiss_elem:
                            await surface.click(dismiss_elem)
                            self.attempt_counts[key] = current_attempts + 1
                            self.recovery_records.append({
                                "step_id": step.id,
                                "condition": rule.condition,
                                "action": "dismiss_interstitial",
                                "attempt": current_attempts + 1,
                                "max_attempts": rule.max_attempts,
                                "retry_allowed": True,
                                "reason": reason,
                            })
                            return True
                    except Exception:
                        continue

                elif rule.condition == "LOADING_SPINNER":
                    try:
                        is_spinner_gone = await surface.wait_for_state("element_absent", ".spinner, .loading-indicator", timeout_ms=rule.timeout_ms)
                        if is_spinner_gone:
                            self.attempt_counts[key] = current_attempts + 1
                            self.recovery_records.append({
                                "step_id": step.id,
                                "condition": rule.condition,
                                "action": "wait_spinner_absent",
                                "attempt": current_attempts + 1,
                                "max_attempts": rule.max_attempts,
                                "retry_allowed": True,
                                "reason": reason,
                            })
                            return True
                    except Exception:
                        continue

        return False
