"""
Checkpoint & Condition Evaluation Engine.
Evaluates Preconditions, Postconditions, Invariants, and Any-Of Decision Branches.
"""
from typing import Dict, Any, Optional
import re
from app.core.models import Precondition, Postcondition, PostconditionBranch, OutcomeType
from app.core.surface_adapter import SurfaceAdapter


class CheckpointEvaluationResult:
    def __init__(
        self,
        passed: bool,
        outcome_type: OutcomeType = OutcomeType.SUCCESS,
        outcome_code: Optional[str] = None,
        message: Optional[str] = None,
    ):
        self.passed = passed
        self.outcome_type = outcome_type
        self.outcome_code = outcome_code
        self.message = message


class CheckpointEngine:
    """Evaluates surface assertions and outcomes against declared capability contracts."""

    @staticmethod
    async def evaluate_precondition(
        precondition: Precondition,
        surface: SurfaceAdapter,
    ) -> bool:
        """Verify surface invariant before step execution."""
        if precondition.type == "route_matches":
            if precondition.pattern:
                return await surface.wait_for_state("route_matches", precondition.pattern, timeout_ms=3000)
        elif precondition.type == "element_present" and precondition.target:
            try:
                elem = await surface.resolve_target(precondition.target.model_dump(), timeout_ms=3000)
                return elem is not None
            except Exception:
                return False
        return True

    @staticmethod
    async def evaluate_postcondition(
        postcondition: Optional[Postcondition],
        surface: SurfaceAdapter,
        extracted_data: Optional[Dict[str, Any]] = None,
    ) -> CheckpointEvaluationResult:
        """
        Evaluates step or flow postcondition.
        Handles 'any_of' branching to distinguish SUCCESS vs BUSINESS_OUTCOME.
        """
        if not postcondition:
            return CheckpointEvaluationResult(passed=True)

        # 1. Any-Of Branching (e.g. Success Table vs Not Found Error Banner)
        if postcondition.type == "any_of" and postcondition.any_of:
            for branch in postcondition.any_of:
                # Check condition type
                if branch.condition_type == "element_present" and branch.target:
                    try:
                        elem = await surface.resolve_target(branch.target.model_dump(), timeout_ms=2500)
                        if elem:
                            return CheckpointEvaluationResult(
                                passed=True,
                                outcome_type=branch.outcome_type,
                                outcome_code=branch.outcome_code,
                                message=branch.message or f"Matched branch '{branch.id}'",
                            )
                    except Exception:
                        continue

                elif branch.condition_type == "text_present" and branch.text_pattern:
                    is_present = await surface.wait_for_state("text_present", branch.text_pattern, timeout_ms=2500)
                    if is_present:
                        return CheckpointEvaluationResult(
                            passed=True,
                            outcome_type=branch.outcome_type,
                            outcome_code=branch.outcome_code,
                            message=branch.message or f"Found text pattern: '{branch.text_pattern}'",
                        )

            # None of the declared branches matched
            return CheckpointEvaluationResult(
                passed=False,
                outcome_type=OutcomeType.HARD_FAILURE,
                message="None of the expected postcondition branches were satisfied.",
            )

        # 2. Output Populated Check
        if postcondition.type == "output_populated" and postcondition.field:
            if extracted_data and extracted_data.get(postcondition.field) is not None:
                return CheckpointEvaluationResult(passed=True)
            return CheckpointEvaluationResult(
                passed=False,
                outcome_type=OutcomeType.HARD_FAILURE,
                message=f"Required output field '{postcondition.field}' was empty or null.",
            )

        # 3. Simple Element Present
        if postcondition.type == "element_present" and postcondition.target:
            try:
                elem = await surface.resolve_target(postcondition.target.model_dump(), timeout_ms=4000)
                return CheckpointEvaluationResult(passed=elem is not None)
            except Exception as e:
                return CheckpointEvaluationResult(
                    passed=False,
                    outcome_type=OutcomeType.HARD_FAILURE,
                    message=f"Element not present: {e}",
                )

        return CheckpointEvaluationResult(passed=True)
