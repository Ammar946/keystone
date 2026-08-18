"""
Deterministic Replay Engine (Zero-LLM Production Execution Engine).
Replays compiled capability artifacts with caller inputs, evaluates cascading locators,
extracts typed outputs, and classifies outcomes into the 3-Tier Error Taxonomy with
native Human-in-the-Loop (HITL) same-session live escalation support.
"""
from typing import Dict, Any, Optional, List, Callable
import time
import uuid
import re
import os
import json
from app.core.models import (
    CapabilityArtifact,
    Step,
    ActionType,
    OutcomeType,
    RiskLevel,
    TenantOverride,
)
from app.core.error_taxonomy import (
    ReplayResult,
    StepExecutionRecord,
    DiagnosticContext,
)
from app.core.surface_adapter import SurfaceAdapter, ControlOwner, ExecutionState
from app.adapters.playwright_adapter import PlaywrightSurfaceAdapter
from app.safety.policy_gate import PolicyGate, PolicyViolationError
from app.engine.checkpoint_engine import CheckpointEngine
from app.engine.recovery_handler import RecoveryHandler
from app.hitl.escalation_manager import HITLEscalationManager


class DeterministicReplayEngine:
    """Pure deterministic capability replay engine with Zero LLM in the loop."""

    def __init__(
        self,
        surface_adapter: Optional[SurfaceAdapter] = None,
        escalation_manager: Optional[HITLEscalationManager] = None,
    ):
        self.surface: Optional[SurfaceAdapter] = surface_adapter
        self.escalation_manager: Optional[HITLEscalationManager] = escalation_manager
        self.recovery_handler = RecoveryHandler()
        self._owns_surface: bool = (surface_adapter is None)

    def _interpolate_value(self, template: Optional[str], inputs: Dict[str, Any]) -> str:
        """Inject runtime parameter values into string templates (e.g. {{ inputs.member_id }})."""
        if not template:
            return ""
        result = template
        for k, v in inputs.items():
            result = result.replace(f"{{{{ inputs.{k} }}}}", str(v))
            result = result.replace(f"{{{{inputs.{k}}}}}", str(v))
        return result

    def _transform_extracted_value(self, raw_val: str, transform: Optional[str]) -> Any:
        """Apply deterministic transformations to extracted strings."""
        if not raw_val:
            return None
        raw_val = raw_val.strip()
        if transform == "strip":
            return raw_val
        elif transform == "parse_currency":
            # Extract currency numbers like "$12,450.75" -> 12450.75
            clean = re.sub(r"[^\d\.]", "", raw_val)
            try:
                return float(clean)
            except ValueError:
                return raw_val
        elif transform == "parse_number":
            clean = re.sub(r"[^\d\.]", "", raw_val)
            try:
                return float(clean) if "." in clean else int(clean)
            except ValueError:
                return raw_val
        elif transform == "upper":
            return raw_val.upper()
        return raw_val

    async def replay(
        self,
        artifact: CapabilityArtifact,
        inputs: Dict[str, Any],
        tenant_override: Optional[TenantOverride] = None,
        headless: bool = True,
        external_session_id: Optional[str] = None,
        enable_hitl: bool = True,
        auto_approve_hitl: bool = False,
        hitl_callback: Optional[Callable] = None,
        evidence_dir: Optional[str] = None,
    ) -> ReplayResult:
        """
        Execute deterministic replay of a capability artifact.
        """
        run_id = f"run_{uuid.uuid4().hex[:8]}"
        session_id = external_session_id or f"sess_{uuid.uuid4().hex[:8]}"
        start_time = time.time()
        step_traces: List[StepExecutionRecord] = []
        extracted_outputs: Dict[str, Any] = {}
        human_interventions: List[Dict[str, Any]] = []

        # 1. Base URL & Route Resolution
        base_url = (
            tenant_override.base_url
            if (tenant_override and tenant_override.base_url)
            else artifact.entry_point.default_base_url
        )
        entry_point = f"{base_url.rstrip('/')}/{artifact.entry_point.route.lstrip('/')}"

        # 2. Surface Initialization
        if self.surface is None:
            self.surface = PlaywrightSurfaceAdapter()
            await self.surface.initialize(session_id=session_id, entry_point=entry_point, headless=headless)
            self._owns_surface = True

        # 3. Escalation Manager Setup
        if enable_hitl and self.escalation_manager is None:
            self.escalation_manager = HITLEscalationManager(
                surface=self.surface,
                evidence_dir=evidence_dir or "evidence/replay-hitl",
            )

        # 4. Policy Gate with Dynamic Domain & Route allowlist
        allowed_domains = list(artifact.entry_point.allowed_domains)
        if tenant_override and tenant_override.base_url:
            allowed_domains.append(tenant_override.base_url)

        policy_gate = PolicyGate(
            policy=artifact.policy,
            allowed_domains=allowed_domains,
            allowed_routes=artifact.policy.allowed_routes,
        )

        try:
            # 5. Top-Level Preconditions Check
            for pre in artifact.preconditions:
                passed = await CheckpointEngine.evaluate_precondition(pre, self.surface)
                if not passed:
                    return ReplayResult(
                        run_id=run_id,
                        capability_id=artifact.capability_id,
                        version=artifact.version,
                        session_id=session_id,
                        status=OutcomeType.HARD_FAILURE,
                        message=f"Precondition failed: {pre.message or pre.type}",
                        duration_ms=(time.time() - start_time) * 1000,
                        steps_executed=0,
                        step_trace=step_traces,
                    )

            # 6. Sequential Step Execution
            for step_idx, step in enumerate(artifact.steps):
                step_start = time.time()
                current_state = await self.surface.observe(capture_screenshot=False)

                # A. Pre-Action Policy & Risk Gate
                policy_decision = policy_gate.evaluate_step(
                    step=step,
                    current_url=current_state.url_or_window,
                    human_approved=False,
                )

                # B. High-Risk / Irreversible Action Encountered
                if policy_decision.decision == "REQUIRE_HITL":
                    if enable_hitl and self.escalation_manager:
                        # 1. Raise Intervention Package on the same live session
                        intervention_pkg = await self.escalation_manager.raise_intervention_request(
                            capability_id=artifact.capability_id,
                            step=step,
                            step_index=step_idx + 1,
                            reason=policy_decision.reason,
                        )
                        human_interventions.append(intervention_pkg)

                        # 2. Operator Resolution Seam
                        if auto_approve_hitl:
                            # Auto-approve takeover: perform action in iframe and confirm
                            if step.target:
                                resolved_elem = await self.surface.resolve_target(
                                    step.target.model_dump(),
                                    timeout_ms=step.timeout_ms,
                                    scope=step.target.scope,
                                    frame_context=step.target.frame_context,
                                )
                                await self.surface.click(resolved_elem)
                            await self.escalation_manager.complete_human_takeover(
                                operator_id="operator_lead_01",
                                action_taken=f"Authorized high-risk step '{step.id}'",
                                resume_signal=True,
                            )
                            self.escalation_manager.confirm_resumption_complete()

                        elif hitl_callback:
                            # Custom operator callback
                            resumed = await hitl_callback(self.surface, step, intervention_pkg)
                            if not resumed:
                                return ReplayResult(
                                    run_id=run_id,
                                    capability_id=artifact.capability_id,
                                    version=artifact.version,
                                    session_id=session_id,
                                    status=OutcomeType.HARD_FAILURE,
                                    message="Human operator aborted intervention.",
                                    steps_executed=step_idx + 1,
                                    duration_ms=(time.time() - start_time) * 1000,
                                    step_trace=step_traces,
                                    human_interventions=human_interventions,
                                )
                            self.escalation_manager.confirm_resumption_complete()
                        else:
                            # Return ESCALATED state if unattended without interactive takeover
                            return ReplayResult(
                                run_id=run_id,
                                capability_id=artifact.capability_id,
                                version=artifact.version,
                                session_id=session_id,
                                status=OutcomeType.ESCALATED,
                                outcome_code="HIGH_RISK_GATE",
                                message=policy_decision.reason,
                                steps_executed=step_idx,
                                duration_ms=(time.time() - start_time) * 1000,
                                step_trace=step_traces,
                                human_interventions=human_interventions,
                                error=DiagnosticContext(
                                    step_id=step.id,
                                    step_index=step_idx,
                                    current_url=current_state.url_or_window,
                                    expected="Human Authorization",
                                    observed="Blocked by Pre-Action Safety Gate",
                                ),
                            )

                        # Step trace for resumed action
                        step_traces.append(
                            StepExecutionRecord(
                                step_id=step.id,
                                action=step.action.value,
                                target_description=step.target.description if step.target else None,
                                matched_strategy="hitl_human_takeover",
                                strategy_confidence=1.0,
                                duration_ms=(time.time() - step_start) * 1000,
                                status="SUCCESS",
                            )
                        )
                        continue
                    else:
                        # Escalation disabled
                        return ReplayResult(
                            run_id=run_id,
                            capability_id=artifact.capability_id,
                            version=artifact.version,
                            session_id=session_id,
                            status=OutcomeType.ESCALATED,
                            outcome_code="HIGH_RISK_GATE",
                            message=policy_decision.reason,
                            steps_executed=step_idx,
                            duration_ms=(time.time() - start_time) * 1000,
                            step_trace=step_traces,
                        )

                # C. Normal Step Execution on Surface
                resolved_elem = None
                matched_strategy = "N/A"
                confidence = 1.0

                try:
                    if step.target:
                        target_dict = step.target.model_dump()
                        # Apply tenant locator overrides if present
                        if tenant_override and step.id in tenant_override.locator_overrides:
                            target_dict["locators"] = [
                                loc.model_dump() for loc in tenant_override.locator_overrides[step.id]
                            ] + target_dict["locators"]

                        resolved_elem = await self.surface.resolve_target(
                            target_spec=target_dict,
                            timeout_ms=step.timeout_ms,
                            scope=step.target.scope,
                            frame_context=step.target.frame_context,
                        )
                        matched_strategy = resolved_elem.matched_strategy
                        confidence = resolved_elem.confidence

                    # Perform Action Verb
                    if step.action == ActionType.TYPE:
                        val_to_type = self._interpolate_value(step.value_template, inputs)
                        await self.surface.type_text(resolved_elem, val_to_type)

                    elif step.action == ActionType.CLICK:
                        await self.surface.click(resolved_elem)

                    elif step.action == ActionType.SELECT:
                        val_to_select = self._interpolate_value(step.value_template, inputs)
                        await self.surface.select_option(resolved_elem, val_to_select)

                    elif step.action == ActionType.EXTRACT:
                        for ext in step.extractions:
                            raw_val = ""
                            if ext.selector:
                                target_spec = {"locators": [{"strategy": "xpath_structural", "value": ext.selector}]}
                                ext_elem = await self.surface.resolve_target(target_spec, timeout_ms=3000)
                                raw_val = await self.surface.read_text(ext_elem)
                            elif resolved_elem:
                                raw_val = await self.surface.read_text(resolved_elem)

                            extracted_outputs[ext.field] = self._transform_extracted_value(raw_val, ext.transform)

                except Exception as step_err:
                    # Attempt Bounded Runtime Recovery
                    recovered = await self.recovery_handler.try_recover(step, self.surface, step_err)
                    if recovered:
                        # Retry Step once after recovery
                        if step.target:
                            resolved_elem = await self.surface.resolve_target(step.target.model_dump(), timeout_ms=step.timeout_ms)
                        if step.action == ActionType.TYPE:
                            val_to_type = self._interpolate_value(step.value_template, inputs)
                            await self.surface.type_text(resolved_elem, val_to_type)
                        elif step.action == ActionType.CLICK:
                            await self.surface.click(resolved_elem)
                        elif step.action == ActionType.SELECT:
                            val_to_select = self._interpolate_value(step.value_template, inputs)
                            await self.surface.select_option(resolved_elem, val_to_select)
                    else:
                        # Hard Failure
                        step_traces.append(
                            StepExecutionRecord(
                                step_id=step.id,
                                action=step.action.value,
                                duration_ms=(time.time() - step_start) * 1000,
                                status="FAILED",
                                error_message=str(step_err),
                            )
                        )
                        return ReplayResult(
                            run_id=run_id,
                            capability_id=artifact.capability_id,
                            version=artifact.version,
                            session_id=session_id,
                            status=OutcomeType.HARD_FAILURE,
                            message=f"Step '{step.id}' failed: {step_err}",
                            steps_executed=step_idx + 1,
                            duration_ms=(time.time() - start_time) * 1000,
                            step_trace=step_traces,
                            human_interventions=human_interventions,
                            error=DiagnosticContext(
                                step_id=step.id,
                                step_index=step_idx,
                                current_url=current_state.url_or_window,
                                expected=step.description,
                                observed=str(step_err),
                            ),
                        )

                # D. Checkpoint & Branch Evaluation
                eval_res = await CheckpointEngine.evaluate_postcondition(
                    step.postcondition,
                    self.surface,
                    extracted_data=extracted_outputs,
                )

                step_duration = (time.time() - step_start) * 1000
                step_traces.append(
                    StepExecutionRecord(
                        step_id=step.id,
                        action=step.action.value,
                        target_description=step.target.description if step.target else None,
                        matched_strategy=matched_strategy,
                        strategy_confidence=confidence,
                        duration_ms=step_duration,
                        status="SUCCESS" if eval_res.passed else "FAILED",
                        extracted_data=extracted_outputs if step.action == ActionType.EXTRACT else None,
                    )
                )

                # If an Expected Business Outcome was matched (e.g. MEMBER_NOT_FOUND)
                if eval_res.outcome_type == OutcomeType.BUSINESS_OUTCOME:
                    return ReplayResult(
                        run_id=run_id,
                        capability_id=artifact.capability_id,
                        version=artifact.version,
                        session_id=session_id,
                        status=OutcomeType.BUSINESS_OUTCOME,
                        outcome_code=eval_res.outcome_code or "BUSINESS_OUTCOME",
                        message=eval_res.message or "Expected business outcome reached.",
                        outputs=extracted_outputs,
                        steps_executed=step_idx + 1,
                        duration_ms=(time.time() - start_time) * 1000,
                        step_trace=step_traces,
                        human_interventions=human_interventions,
                    )

                if not eval_res.passed:
                    return ReplayResult(
                        run_id=run_id,
                        capability_id=artifact.capability_id,
                        version=artifact.version,
                        session_id=session_id,
                        status=OutcomeType.HARD_FAILURE,
                        message=f"Postcondition failed on step '{step.id}': {eval_res.message}",
                        steps_executed=step_idx + 1,
                        duration_ms=(time.time() - start_time) * 1000,
                        step_trace=step_traces,
                        human_interventions=human_interventions,
                    )

            # 7. Final Capability Postconditions
            for post in artifact.postconditions:
                post_res = await CheckpointEngine.evaluate_postcondition(post, self.surface, extracted_data=extracted_outputs)
                if not post_res.passed:
                    return ReplayResult(
                        run_id=run_id,
                        capability_id=artifact.capability_id,
                        version=artifact.version,
                        session_id=session_id,
                        status=OutcomeType.HARD_FAILURE,
                        message=f"Capability postcondition failed: {post_res.message}",
                        steps_executed=len(artifact.steps),
                        duration_ms=(time.time() - start_time) * 1000,
                        step_trace=step_traces,
                        human_interventions=human_interventions,
                    )

            if self.escalation_manager:
                self.escalation_manager.mark_completed()

            # Execution Succeeded Cleanly
            return ReplayResult(
                run_id=run_id,
                capability_id=artifact.capability_id,
                version=artifact.version,
                session_id=session_id,
                status=OutcomeType.SUCCESS,
                message="Replay completed successfully.",
                outputs=extracted_outputs,
                steps_executed=len(artifact.steps),
                duration_ms=(time.time() - start_time) * 1000,
                step_trace=step_traces,
                human_interventions=human_interventions,
            )

        finally:
            if self._owns_surface and self.surface:
                await self.surface.close()
                self.surface = None
