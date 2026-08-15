"""
Artifact Compiler & Validation Pipeline.
Normalizes raw discovery observations and action transcripts into typed, versioned Capability Artifacts.
Performs schema validation, parameter template synthesis, and multi-strategy locator construction.
"""
from typing import Dict, Any, List, Optional
import os
import json
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
)
from app.safety.pii_redactor import PIIRedactor


class ArtifactCompiler:
    """Compiles discovery transcripts into production Capability Artifacts."""

    @classmethod
    def compile_member_balance_capability(
        cls,
        entry_url: str = "http://localhost:8080/console/members",
    ) -> CapabilityArtifact:
        """
        Constructs and validates the core member balance lookup capability artifact.
        """
        artifact = CapabilityArtifact(
            schema_version="1.0.0",
            capability_id="corebank.member.get_balance",
            version="1.0.0",
            status=CapabilityStatus.APPROVED,
            name="Lookup Member Account Balances",
            description="Searches CoreBank console for a member by account ID and extracts savings and checking balances.",
            application=ApplicationMetadata(
                vendor="Apex",
                product="CoreBank",
                min_version="4.0.0",
                supported_variants=["default", "tenant_branded"],
            ),
            entry_point=TargetEntryPoint(
                route="/console/members",
                default_base_url="http://localhost:8080",
                allowed_domains=["localhost:8080", "127.0.0.1:8080"],
            ),
            inputs_schema={
                "member_id": InputParameter(
                    type="string",
                    description="5-digit member account identifier (e.g. '10042')",
                    required=True,
                    sensitive=False,
                )
            },
            outputs_schema={
                "member_name": OutputField(type="string", description="Full legal name of member", nullable=False),
                "account_status": OutputField(type="string", description="Account standing (ACTIVE / FROZEN)", nullable=False),
                "savings_balance": OutputField(type="decimal", description="Ledger balance for regular savings account", nullable=True),
                "checking_balance": OutputField(type="decimal", description="Ledger balance for checking account", nullable=True),
            },
            preconditions=[
                Precondition(
                    type="route_matches",
                    pattern="/console/members",
                    message="Must be on member console root route",
                ),
            ],
            steps=[
                Step(
                    id="step_enter_member_id",
                    description="Enter member ID into search query input",
                    action=ActionType.TYPE,
                    risk_level=RiskLevel.READ_ONLY,
                    idempotent=True,
                    retryable=True,
                    target=TargetSpec(
                        description="Member ID input field in search form",
                        scope="form[name='searchForm']",
                        locators=[
                            LocatorCandidate(
                                strategy="accessibility",
                                value="textbox[name='Member ID / Account #']",
                                priority=1,
                                confidence=0.98,
                                reasoning="Semantic accessible textbox role with aria label",
                            ),
                            LocatorCandidate(
                                strategy="css_scoped",
                                value="input.legacy-input[name='memberId']",
                                priority=2,
                                confidence=0.88,
                                reasoning="Scoped CSS class in legacy searchForm",
                            ),
                            LocatorCandidate(
                                strategy="xpath_structural",
                                value=".//td[contains(text(),'Member ID')]/following-sibling::td/input",
                                priority=3,
                                confidence=0.75,
                                reasoning="Table cell label adjacency fallback",
                            ),
                        ],
                    ),
                    value_template="{{ inputs.member_id }}",
                    postcondition=Postcondition(
                        type="value_matches",
                        expected="{{ inputs.member_id }}",
                    ),
                    recovery_rules=[
                        {
                            "condition": "TRANSIENT_INTERSTITIAL",
                            "action": "dismiss_modal",
                            "target": {
                                "locators": [
                                    {"strategy": "accessibility", "value": "button[name='Dismiss Notice']", "confidence": 0.95},
                                    {"strategy": "css_scoped", "value": "#btn_dismiss_notice", "confidence": 0.90},
                                ]
                            },
                            "timeout_ms": 3000,
                            "max_attempts": 1,
                        }
                    ],
                ),
                Step(
                    id="step_click_search",
                    description="Submit search form to retrieve member records",
                    action=ActionType.CLICK,
                    risk_level=RiskLevel.READ_ONLY,
                    idempotent=True,
                    retryable=True,
                    target=TargetSpec(
                        description="Search records submit button",
                        scope="form[name='searchForm']",
                        locators=[
                            LocatorCandidate(
                                strategy="accessibility",
                                value="button[name='Search Records']",
                                priority=1,
                                confidence=0.96,
                                reasoning="Accessible button name query",
                            ),
                            LocatorCandidate(
                                strategy="css_scoped",
                                value="button[type='submit'][name='btnSearch']",
                                priority=2,
                                confidence=0.90,
                                reasoning="Scoped submit button selector",
                            ),
                            LocatorCandidate(
                                strategy="xpath_structural",
                                value=".//button[text()='Search']",
                                priority=3,
                                confidence=0.78,
                                reasoning="Direct button text match",
                            ),
                        ],
                    ),
                    postcondition=Postcondition(
                        type="any_of",
                        any_of=[
                            PostconditionBranch(
                                id="branch_member_found",
                                condition_type="element_present",
                                target=TargetSpec(
                                    locators=[
                                        LocatorCandidate(
                                            strategy="css_scoped",
                                            value="table.account-summary-table",
                                            confidence=0.95,
                                        )
                                    ]
                                ),
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
                ),
                Step(
                    id="step_extract_balances",
                    description="Extract member name, status, and account ledger balances",
                    action=ActionType.EXTRACT,
                    risk_level=RiskLevel.READ_ONLY,
                    idempotent=True,
                    retryable=True,
                    extractions=[
                        {
                            "field": "member_name",
                            "strategy": "xpath_structural",
                            "selector": "//td[@id='lbl_memberName']",
                            "transform": "strip",
                            "nullable": False,
                        },
                        {
                            "field": "account_status",
                            "strategy": "xpath_structural",
                            "selector": "//span[@id='badge_status']",
                            "transform": "strip",
                            "nullable": False,
                        },
                        {
                            "field": "savings_balance",
                            "strategy": "xpath_structural",
                            "selector": "//table[@id='tbl_balances']//tr[td[contains(text(),'Regular Savings')]]/td[@class='bal-val']",
                            "transform": "parse_currency",
                            "nullable": True,
                        },
                        {
                            "field": "checking_balance",
                            "strategy": "xpath_structural",
                            "selector": "//table[@id='tbl_balances']//tr[td[contains(text(),'Premier Checking') or td[contains(text(),'Standard Checking')]]]/td[@class='bal-val']",
                            "transform": "parse_currency",
                            "nullable": True,
                        },
                    ],
                ),
            ],
            postconditions=[
                Postcondition(
                    type="output_populated",
                    field="member_name",
                )
            ],
            policy=SafetyPolicy(
                risk_level=RiskLevel.READ_ONLY,
                allowed_actions=["click", "type", "extract", "wait", "scroll", "navigate"],
                allowed_routes=["^/console/.*$"],
                requires_confirmation_on_risk=True,
            ),
        )
        return artifact

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
