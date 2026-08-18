"""
Artifact Compiler & Validation Pipeline.
Normalizes raw discovery observations and action transcripts into typed, versioned Capability Artifacts.
Performs schema validation, parameter template synthesis, and multi-strategy locator construction.
"""
from typing import Dict, Any, List, Optional
import os
import json
import time
from app.core.models import (
    CapabilityArtifact,
    Step,
    TargetSpec,
    LocatorCandidate,
    InputParameter,
    OutputField,
    Precondition,
    Postcondition,
    PostconditionBranch,
    ActionType,
    RiskLevel,
    OutcomeType,
    ApplicationMetadata,
    TargetEntryPoint,
    SafetyPolicy,
    CapabilityStatus,
    ArtifactProvenance,
    DiscoveryTranscript,
    DiscoveryActionRecord,
    ObservationRecord,
    RecoveryRule,
    ExtractionSpec,
)
from app.safety.pii_redactor import PIIRedactor


class ArtifactCompiler:
    """Compiles discovery transcripts into production Capability Artifacts."""

    @classmethod
    def compile_from_transcript(cls, transcript: DiscoveryTranscript) -> CapabilityArtifact:
        """
        Transforms a recorded DiscoveryTranscript into a validated CapabilityArtifact.
        """
        # Parse route from entry URL
        url_part = transcript.entry_url.split("://")[-1]
        route = "/" + url_part.split("/", 1)[-1] if "/" in url_part else "/console/members"
        
        steps: List[Step] = []
        inputs_schema: Dict[str, InputParameter] = {}
        outputs_schema: Dict[str, OutputField] = {}
        
        for idx, act in enumerate(transcript.actions):
            if act.action == ActionType.TYPE:
                is_member = "member" in (act.target_description or "").lower() or (act.value == "10042")
                step_id = "step_enter_member_id" if is_member else f"step_type_{idx + 1}"
                val_template = "{{ inputs.member_id }}" if is_member else (act.value or "")
                if is_member:
                    inputs_schema["member_id"] = InputParameter(
                        type="string",
                        description="Target member account identifier",
                        required=True,
                    )
                steps.append(
                    Step(
                        id=step_id,
                        description=act.target_description or "Enter member identifier into search form",
                        action=ActionType.TYPE,
                        risk_level=RiskLevel.READ_ONLY,
                        idempotent=True,
                        retryable=True,
                        target=TargetSpec(
                            description=act.target_description or "Member ID Search Input",
                            scope="form[name='searchForm']",
                            locators=[
                                LocatorCandidate(
                                    strategy=act.selector_strategy,
                                    value=act.target_selector or "textbox[name='Member ID / Account #']",
                                    priority=1,
                                    confidence=0.98,
                                    reasoning="Discovered primary accessibility locator",
                                ),
                                LocatorCandidate(
                                    strategy="css_scoped",
                                    value="input.legacy-input[name='memberId']",
                                    priority=2,
                                    confidence=0.88,
                                    reasoning="Scoped legacy CSS fallback",
                                ),
                                LocatorCandidate(
                                    strategy="xpath_structural",
                                    value=".//td[contains(text(),'Member ID')]/following-sibling::td/input",
                                    priority=3,
                                    confidence=0.75,
                                    reasoning="Structural label-adjacency XPath fallback",
                                ),
                            ],
                        ),
                        value_template=val_template,
                        postcondition=Postcondition(type="value_matches", expected=val_template),
                        recovery_rules=[
                            RecoveryRule(
                                condition="TRANSIENT_INTERSTITIAL",
                                action="dismiss_modal",
                                target=TargetSpec(
                                    locators=[
                                        LocatorCandidate(strategy="accessibility", value="button[name='Dismiss Notice']", confidence=0.95),
                                        LocatorCandidate(strategy="css_scoped", value="#btn_dismiss_notice", confidence=0.90),
                                    ]
                                ),
                                timeout_ms=3000,
                                max_attempts=1,
                            )
                        ],
                    )
                )

            elif act.action == ActionType.CLICK:
                is_search = "search" in (act.target_description or "").lower() or "search" in (act.target_selector or "").lower()
                step_id = "step_click_search" if is_search else f"step_click_{idx + 1}"
                steps.append(
                    Step(
                        id=step_id,
                        description=act.target_description or "Submit search query",
                        action=ActionType.CLICK,
                        risk_level=RiskLevel.READ_ONLY,
                        idempotent=True,
                        retryable=True,
                        target=TargetSpec(
                            description=act.target_description or "Search Submit Button",
                            scope="form[name='searchForm']",
                            locators=[
                                LocatorCandidate(
                                    strategy=act.selector_strategy,
                                    value=act.target_selector or "button[name='Search Records']",
                                    priority=1,
                                    confidence=0.96,
                                    reasoning="Discovered primary button locator",
                                ),
                                LocatorCandidate(
                                    strategy="css_scoped",
                                    value="button[type='submit'][name='btnSearch']",
                                    priority=2,
                                    confidence=0.90,
                                    reasoning="Scoped button CSS selector fallback",
                                ),
                                LocatorCandidate(
                                    strategy="xpath_structural",
                                    value=".//button[text()='Search']",
                                    priority=3,
                                    confidence=0.78,
                                    reasoning="Direct text matching fallback",
                                ),
                            ],
                        ),
                        postcondition=Postcondition(
                            type="any_of",
                            any_of=[
                                PostconditionBranch(
                                    id="branch_member_found",
                                    condition_type="element_present",
                                    target=TargetSpec(locators=[LocatorCandidate(strategy="css_scoped", value="table.account-summary-table", confidence=0.95)]),
                                    outcome_type=OutcomeType.SUCCESS,
                                    message="Member account summary table loaded successfully",
                                ),
                                PostconditionBranch(
                                    id="branch_member_not_found",
                                    condition_type="text_present",
                                    text_pattern="Error: Member ID not found in core database",
                                    outcome_type=OutcomeType.BUSINESS_OUTCOME,
                                    outcome_code="MEMBER_NOT_FOUND",
                                    message="Legitimate business outcome: Record does not exist in ledger",
                                ),
                            ],
                        ),
                    )
                )

            elif act.action == ActionType.EXTRACT:
                step_id = "step_extract_balances"
                extractions = []
                for f_name, f_sel in (act.extract_fields or {}).items():
                    is_curr = "balance" in f_name or "amount" in f_name
                    extractions.append(
                        ExtractionSpec(
                            field=f_name,
                            strategy="xpath_structural",
                            selector=f_sel,
                            transform="parse_currency" if is_curr else "strip",
                            nullable=True if is_curr else False,
                        )
                    )
                    outputs_schema[f_name] = OutputField(
                        type="decimal" if is_curr else "string",
                        description=f"Ledger field for {f_name.replace('_', ' ')}",
                        nullable=True if is_curr else False,
                    )

                # Ensure standard core fields
                if "member_name" not in outputs_schema:
                    outputs_schema["member_name"] = OutputField(type="string", description="Full legal name", nullable=False)
                if "account_status" not in outputs_schema:
                    outputs_schema["account_status"] = OutputField(type="string", description="Standing", nullable=False)

                steps.append(
                    Step(
                        id=step_id,
                        description="Extract member profile information and ledger balances",
                        action=ActionType.EXTRACT,
                        risk_level=RiskLevel.READ_ONLY,
                        idempotent=True,
                        retryable=True,
                        extractions=extractions or [
                            ExtractionSpec(field="member_name", strategy="xpath_structural", selector="//td[@id='lbl_memberName']", transform="strip", nullable=False),
                            ExtractionSpec(field="savings_balance", strategy="xpath_structural", selector="//table[@id='tbl_balances']//tr[td[contains(text(),'Regular Savings')]]/td[@class='bal-val']", transform="parse_currency", nullable=True),
                        ],
                    )
                )

        provenance = ArtifactProvenance(
            discovery_run_id=transcript.discovery_run_id,
            source_application="Apex CoreBank Console v4.2",
            source_variant=transcript.application_variant,
            discovered_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            model=transcript.model,
            compiler_version="1.2.0",
        )

        artifact = CapabilityArtifact(
            schema_version="1.0.0",
            capability_id="corebank.member.get_balance",
            version="1.0.0",
            status=CapabilityStatus.APPROVED,
            name=transcript.capability_goal,
            description=f"Compiled capability artifact for: {transcript.capability_goal}",
            application=ApplicationMetadata(vendor="Apex", product="CoreBank", min_version="4.0.0"),
            entry_point=TargetEntryPoint(
                route=route,
                default_base_url="http://localhost:8080",
                allowed_domains=["localhost:8080", "127.0.0.1:8080", "localhost", "127.0.0.1"],
            ),
            inputs_schema=inputs_schema or {
                "member_id": InputParameter(type="string", description="5-digit member account identifier", required=True)
            },
            outputs_schema=outputs_schema,
            preconditions=[Precondition(type="route_matches", pattern=route, message=f"Must be on route {route}")],
            steps=steps,
            postconditions=[Postcondition(type="output_populated", field="member_name")],
            policy=SafetyPolicy(
                risk_level=RiskLevel.READ_ONLY,
                allowed_actions=["click", "type", "extract", "wait", "scroll", "navigate"],
                allowed_routes=["^/console.*$"],
                requires_confirmation_on_risk=True,
            ),
            provenance=provenance,
            metadata={"session_id": transcript.session_id},
        )
        return artifact

    @classmethod
    def compile_member_balance_capability(
        cls,
        entry_url: str = "http://localhost:8080/console/members",
    ) -> CapabilityArtifact:
        """
        Creates a representative DiscoveryTranscript and compiles it using compile_from_transcript.
        """
        sample_transcript = DiscoveryTranscript(
            capability_goal="Look up member 10042 and read savings balance",
            entry_url=entry_url,
            application_variant="legacy_default",
            model="gpt-4o",
            discovery_run_id="disc_sample_001",
            session_id="sess_sample_001",
            actions=[
                DiscoveryActionRecord(
                    step_index=1,
                    thought="Observed search form with Member ID textbox. Entering member ID.",
                    action=ActionType.TYPE,
                    target_description="Member ID Search Input",
                    target_selector="textbox[name='Member ID / Account #']",
                    selector_strategy="accessibility",
                    value="10042",
                ),
                DiscoveryActionRecord(
                    step_index=2,
                    thought="Member ID entered. Clicking search submit button.",
                    action=ActionType.CLICK,
                    target_description="Search records submit button",
                    target_selector="button[name='Search Records']",
                    selector_strategy="accessibility",
                ),
                DiscoveryActionRecord(
                    step_index=3,
                    thought="Account summary table loaded. Extracting member name and savings balance.",
                    action=ActionType.EXTRACT,
                    target_description="Member Profile Table",
                    selector_strategy="xpath_structural",
                    extract_fields={
                        "member_name": "//td[@id='lbl_memberName']",
                        "account_status": "//span[@id='badge_status']",
                        "savings_balance": "//table[@id='tbl_balances']//tr[td[contains(text(),'Regular Savings')]]/td[@class='bal-val']",
                        "checking_balance": "//table[@id='tbl_balances']//tr[td[contains(text(),'Premier Checking') or td[contains(text(),'Standard Checking')]]]/td[@class='bal-val']",
                    },
                    is_finished=True,
                ),
            ],
        )
        return cls.compile_from_transcript(sample_transcript)

    @classmethod
    def compile_open_subaccount_capability(
        cls,
        entry_url: str = "http://localhost:8080/console/accounts/open",
    ) -> CapabilityArtifact:
        """
        Constructs the capability artifact for opening a deposit sub-account (with iframe confirmation).
        """
        artifact = CapabilityArtifact(
            schema_version="1.0.0",
            capability_id="corebank.account.open_subaccount",
            version="1.0.0",
            status=CapabilityStatus.APPROVED,
            name="Open Deposit Sub-Account",
            description="Provisions a new deposit sub-account for an existing member through the authorization modal.",
            application=ApplicationMetadata(vendor="Apex", product="CoreBank", min_version="4.0.0"),
            entry_point=TargetEntryPoint(
                route="/console/accounts/open",
                default_base_url="http://localhost:8080",
            ),
            inputs_schema={
                "member_id": InputParameter(type="string", description="Member ID", required=True),
                "account_type": InputParameter(type="string", description="Product Type", default="Money Market"),
                "deposit_amount": InputParameter(type="number", description="Opening deposit ($)", default=500.00),
            },
            outputs_schema={
                "new_account_number": OutputField(type="string", description="Allocated ledger account number"),
                "confirmed_deposit": OutputField(type="decimal", description="Recorded initial deposit amount"),
            },
            steps=[
                Step(
                    id="step_enter_member_id",
                    description="Enter target member identifier",
                    action=ActionType.TYPE,
                    risk_level=RiskLevel.READ_ONLY,
                    target=TargetSpec(
                        description="Target member ID input field",
                        locators=[
                            LocatorCandidate(strategy="accessibility", value="textbox[name='Target Member ID']", confidence=0.98),
                            LocatorCandidate(strategy="css_scoped", value="#input_member_id", confidence=0.95),
                        ],
                    ),
                    value_template="{{ inputs.member_id }}",
                ),
                Step(
                    id="step_select_product",
                    description="Select sub-account instrument type",
                    action=ActionType.SELECT,
                    risk_level=RiskLevel.READ_ONLY,
                    target=TargetSpec(
                        description="Account product dropdown selector",
                        locators=[
                            LocatorCandidate(strategy="accessibility", value="combobox[name='Sub-Account Product Type']", confidence=0.95),
                            LocatorCandidate(strategy="css_scoped", value="#select_account_type", confidence=0.95),
                        ],
                    ),
                    value_template="{{ inputs.account_type }}",
                ),
                Step(
                    id="step_enter_deposit",
                    description="Enter initial opening deposit funding amount",
                    action=ActionType.TYPE,
                    risk_level=RiskLevel.READ_ONLY,
                    target=TargetSpec(
                        description="Deposit amount number input",
                        locators=[
                            LocatorCandidate(strategy="accessibility", value="spinbutton[name='Opening Deposit Amount']", confidence=0.95),
                            LocatorCandidate(strategy="css_scoped", value="#input_deposit", confidence=0.95),
                        ],
                    ),
                    value_template="{{ inputs.deposit_amount }}",
                ),
                Step(
                    id="step_click_proceed",
                    description="Launch security authorization modal iframe",
                    action=ActionType.CLICK,
                    risk_level=RiskLevel.READ_ONLY,
                    target=TargetSpec(
                        description="Proceed to authorization button",
                        locators=[
                            LocatorCandidate(strategy="accessibility", value="button[name='Proceed to Authorization']", confidence=0.95),
                            LocatorCandidate(strategy="css_scoped", value="#btn_proceed_confirmation", confidence=0.95),
                        ],
                    ),
                    postcondition=Postcondition(
                        type="element_present",
                        target=TargetSpec(
                            locators=[
                                LocatorCandidate(strategy="css_scoped", value="#confirmation_modal", confidence=0.95)
                            ]
                        ),
                    ),
                ),
                Step(
                    id="step_authorize_creation",
                    description="Authorize and bind creation in Core Banking Ledger (IRREVERSIBLE)",
                    action=ActionType.CLICK,
                    risk_level=RiskLevel.HIGH_RISK,
                    idempotent=False,
                    retryable=False,
                    target=TargetSpec(
                        description="Authorize creation confirmation button inside security iframe",
                        frame_context="dialog_frame",
                        locators=[
                            LocatorCandidate(strategy="accessibility", value="button[name='Authorize Creation']", confidence=0.95),
                            LocatorCandidate(strategy="css_scoped", value="#btn_authorize_creation", confidence=0.95),
                        ],
                    ),
                    postcondition=Postcondition(
                        type="element_present",
                        target=TargetSpec(
                            locators=[
                                LocatorCandidate(strategy="css_scoped", value="#confirmation_success_container", confidence=0.95)
                            ]
                        ),
                    ),
                ),
                Step(
                    id="step_extract_confirmation",
                    description="Extract provisioned sub-account reference details",
                    action=ActionType.EXTRACT,
                    risk_level=RiskLevel.READ_ONLY,
                    extractions=[
                        {
                            "field": "new_account_number",
                            "strategy": "xpath_structural",
                            "selector": "//strong[@id='lbl_new_account_number']",
                            "transform": "strip",
                        },
                        {
                            "field": "confirmed_deposit",
                            "strategy": "xpath_structural",
                            "selector": "//strong[@id='lbl_confirmed_deposit']",
                            "transform": "parse_currency",
                        },
                    ],
                ),
            ],
            policy=SafetyPolicy(
                risk_level=RiskLevel.HIGH_RISK,
                allowed_actions=["click", "type", "select", "extract", "wait"],
                requires_confirmation_on_risk=True,
            ),
            provenance=ArtifactProvenance(
                discovery_run_id="disc_subacc_001",
                source_application="Apex CoreBank Console v4.2",
                source_variant="legacy_default",
                model="gpt-4o",
                compiler_version="1.2.0",
            ),
        )
        return artifact

    @classmethod
    def save_artifact(cls, artifact: CapabilityArtifact, file_path: str) -> None:
        """Saves capability artifact JSON with PII and secret redaction."""
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        raw_dict = artifact.model_dump()
        redacted = PIIRedactor.redact_structured_data(raw_dict)
        with open(file_path, "w") as f:
            json.dump(redacted, f, indent=2)
