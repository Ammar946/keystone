"""
Idempotency-Aware Bounded Runtime Recovery Handler.
Handles known transient conditions (modals, overlays, slow loading spinners)
without blindly retrying non-idempotent actions.
"""
from typing import List, Optional, Dict, Any
from app.core.models import Step, RecoveryRule, RiskLevel
from app.core.surface_adapter import SurfaceAdapter


class RecoveryHandler:
    """Bounded, safe recovery executor for transient runtime conditions."""

    @staticmethod
    async def try_recover(
        step: Step,
        surface: SurfaceAdapter,
        observed_error: Exception,
    ) -> bool:
        """
        Attempts bounded recovery if the step permits retry and matches declared recovery rules.
        """
        # Safety Check: Never retry non-idempotent or high-risk actions automatically
        if not step.idempotent or not step.retryable or step.risk_level == RiskLevel.HIGH_RISK:
            return False

        if not step.recovery_rules:
            return False

        for rule in step.recovery_rules:
            if rule.condition == "TRANSIENT_INTERSTITIAL" and rule.target:
                try:
                    # Attempt to resolve and click dismiss target
                    dismiss_elem = await surface.resolve_target(rule.target.model_dump(), timeout_ms=2000)
                    if dismiss_elem:
                        await surface.click(dismiss_elem)
                        return True
                except Exception:
                    continue

            elif rule.condition == "LOADING_SPINNER":
                # Wait for transient network or loading state
                await surface.wait_for_state("element_absent", ".spinner", timeout_ms=rule.timeout_ms)
                return True

        return False
