"""
Idempotency-Aware Bounded Runtime Recovery Handler.
Handles known transient conditions (modals, overlays, slow loading spinners)
with condition classification and strict max_attempts enforcement.
"""
from typing import List, Optional, Dict, Any
from app.core.models import Step, RecoveryRule, RiskLevel
from app.core.surface_adapter import SurfaceAdapter


class RecoveryHandler:
    """Bounded, safe recovery executor for transient runtime conditions."""

    def __init__(self):
        self.attempt_counts: Dict[str, int] = {}

    async def try_recover(
        self,
        step: Step,
        surface: SurfaceAdapter,
        observed_error: Exception,
    ) -> bool:
        """
        Attempts bounded recovery if:
        1. Action is explicitly declared idempotent and retryable
        2. Action is not HIGH_RISK or IRREVERSIBLE
        3. Observed surface state matches a declared recovery rule
        4. Max attempts threshold has not been exceeded
        """
        # Safety Gate: Never auto-retry non-idempotent or high-risk actions
        if not step.idempotent or not step.retryable or step.risk_level in [RiskLevel.HIGH_RISK, RiskLevel.IRREVERSIBLE]:
            return False

        if not step.recovery_rules:
            return False

        for rule in step.recovery_rules:
            key = f"{step.id}:{rule.condition}"
            current_attempts = self.attempt_counts.get(key, 0)
            
            # Enforce max_attempts bound
            if current_attempts >= rule.max_attempts:
                continue

            if rule.condition == "TRANSIENT_INTERSTITIAL" and rule.target:
                try:
                    # Classify: Check if the interstitial modal or dismiss button is actually present
                    dismiss_elem = await surface.resolve_target(rule.target.model_dump(), timeout_ms=2000)
                    if dismiss_elem:
                        await surface.click(dismiss_elem)
                        self.attempt_counts[key] = current_attempts + 1
                        return True
                except Exception:
                    continue

            elif rule.condition == "LOADING_SPINNER":
                try:
                    is_spinner_gone = await surface.wait_for_state("element_absent", ".spinner, .loading-indicator", timeout_ms=rule.timeout_ms)
                    if is_spinner_gone:
                        self.attempt_counts[key] = current_attempts + 1
                        return True
                except Exception:
                    continue

        return False
