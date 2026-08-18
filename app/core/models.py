"""
Pydantic v2 Models for Capability Artifacts, Locators, Safety Policies,
Tenant Overrides, Discovery Transcripts, and Policy Decisions.
"""
from typing import Dict, List, Optional, Any, Union, Literal
from enum import Enum
import time
from pydantic import BaseModel, Field, model_validator


class CapabilityStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    DEGRADED = "DEGRADED"
    INVALID = "INVALID"


class LocatorStrategyType(str, Enum):
    ACCESSIBILITY = "accessibility"
    ROLE_AND_NAME = "role_and_name"
    CSS_SCOPED = "css_scoped"
    CSS_LEGACY = "css_legacy"
    XPATH_STRUCTURAL = "xpath_structural"
    XPATH_TEXT = "xpath_text"
    TEXT_LABEL_RELATION = "text_label_relation"
    VISUAL_COORDINATES = "visual_coordinates"


class ActionType(str, Enum):
    NAVIGATE = "navigate"
    CLICK = "click"
    TYPE = "type"
    SELECT = "select"
    EXTRACT = "extract"
    WAIT = "wait"
    SCROLL = "scroll"
    CUSTOM = "custom"


class RiskLevel(str, Enum):
    READ_ONLY = "READ_ONLY"
    REVERSIBLE = "REVERSIBLE"
    HIGH_RISK = "HIGH_RISK"
    IRREVERSIBLE = "IRREVERSIBLE"


class OutcomeType(str, Enum):
    SUCCESS = "SUCCESS"
    BUSINESS_OUTCOME = "BUSINESS_OUTCOME"
    RECOVERED = "RECOVERED"
    ESCALATED = "ESCALATED"
    HARD_FAILURE = "HARD_FAILURE"


class RuntimeCondition(str, Enum):
    TRANSIENT_INTERSTITIAL = "TRANSIENT_INTERSTITIAL"
    LOADING_SPINNER = "LOADING_SPINNER"
    ELEMENT_NOT_READY = "ELEMENT_NOT_READY"
    UNKNOWN = "UNKNOWN"


class VisualBBox(BaseModel):
    x: float
    y: float
    width: Optional[float] = None
    height: Optional[float] = None
    viewport_width: int = 1280
    viewport_height: int = 800
    device_scale_factor: float = 1.0


class LocatorCandidate(BaseModel):
    strategy: str = Field(..., description="Locator strategy type (accessibility, css_scoped, xpath, etc.)")
    value: Union[str, Dict[str, Any]] = Field(..., description="Selector query or coordinate specification")
    priority: int = Field(default=1, description="Resolution priority order (lower runs first)")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Estimated resilience score")
    reasoning: Optional[str] = Field(default=None, description="Explanation of why this selector was chosen")
    stability: str = Field(default="HIGH", description="Stability rating: HIGH, MEDIUM, LOW")


class TargetSpec(BaseModel):
    description: Optional[str] = Field(default=None, description="Human-readable purpose of target element")
    scope: Optional[str] = Field(default=None, description="Parent container selector scope (e.g. form[name='search'])")
    frame_context: Optional[str] = Field(default=None, description="Nested iframe selector or URL pattern if applicable")
    locators: List[LocatorCandidate] = Field(default_factory=list, description="Ordered locator fallback chain")
    visual_bbox: Optional[VisualBBox] = Field(default=None, description="Visual coordinate metadata for fallback")


class ExtractionSpec(BaseModel):
    field: str = Field(..., description="Output field name to populate")
    strategy: str = Field(default="xpath_structural", description="Locator extraction method")
    target: Optional[TargetSpec] = None
    selector: Optional[str] = None
    attribute: Optional[str] = None
    transform: Optional[str] = Field(default="strip", description="Post-processing: strip, parse_currency, parse_number, upper")
    nullable: bool = Field(default=True)


class PostconditionBranch(BaseModel):
    id: str
    condition_type: str = Field(default="element_present", description="element_present, text_present, route_matches")
    target: Optional[TargetSpec] = None
    text_pattern: Optional[str] = None
    outcome_type: OutcomeType = OutcomeType.SUCCESS
    outcome_code: Optional[str] = None
    message: Optional[str] = None


class Postcondition(BaseModel):
    type: str = Field(default="element_present", description="element_present, text_present, value_matches, output_populated, any_of")
    expected: Optional[str] = None
    field: Optional[str] = None
    target: Optional[TargetSpec] = None
    text_pattern: Optional[str] = None
    any_of: Optional[List[PostconditionBranch]] = None


class Precondition(BaseModel):
    type: str = Field(default="route_matches", description="route_matches, element_present, authenticated")
    pattern: Optional[str] = None
    target: Optional[TargetSpec] = None
    expected: Optional[str] = None
    message: Optional[str] = None


class RecoveryRule(BaseModel):
    condition: str = Field(..., description="Condition name: TRANSIENT_INTERSTITIAL, LOADING_SPINNER, SESSION_WARNING")
    action: str = Field(default="dismiss_modal", description="dismiss_modal, wait, refresh")
    target: Optional[TargetSpec] = None
    timeout_ms: int = 5000
    max_attempts: int = 1


class Step(BaseModel):
    id: str = Field(..., description="Unique step identifier (e.g. step_enter_member_id)")
    description: Optional[str] = None
    action: ActionType = ActionType.CLICK
    target: Optional[TargetSpec] = None
    value_template: Optional[str] = Field(default=None, description="Jinja2/string template for typed input injection")
    risk_level: RiskLevel = RiskLevel.READ_ONLY
    idempotent: bool = Field(default=True, description="True if safely retryable without duplicate side-effects")
    retryable: bool = Field(default=True, description="True if retry on transient failure is permitted")
    timeout_ms: int = Field(default=5000)
    preconditions: List[Precondition] = Field(default_factory=list)
    postcondition: Optional[Postcondition] = None
    recovery_rules: List[RecoveryRule] = Field(default_factory=list)
    extractions: List[ExtractionSpec] = Field(default_factory=list)


class InputParameter(BaseModel):
    type: str = Field(default="string", description="string, number, boolean, integer")
    description: Optional[str] = None
    required: bool = True
    default: Optional[Any] = None
    sensitive: bool = False


class OutputField(BaseModel):
    type: str = Field(default="string", description="string, number, decimal, boolean, list, object")
    description: Optional[str] = None
    nullable: bool = True
    sample: Optional[Any] = None


class ApplicationMetadata(BaseModel):
    vendor: str = "Apex"
    product: str = "CoreBank"
    min_version: str = "4.0.0"
    supported_variants: List[str] = Field(default_factory=lambda: ["default", "tenant_branded"])


class TargetEntryPoint(BaseModel):
    route: str = "/console/members"
    default_base_url: str = "http://localhost:8080"
    allowed_domains: List[str] = Field(default_factory=lambda: ["localhost:8080", "127.0.0.1:8080"])


class SafetyPolicy(BaseModel):
    risk_level: RiskLevel = RiskLevel.READ_ONLY
    allowed_actions: List[str] = Field(default_factory=lambda: ["click", "type", "select", "extract", "wait", "scroll", "navigate"])
    allowed_routes: List[str] = Field(default_factory=lambda: ["^/console/.*$"])
    requires_confirmation_on_risk: bool = True
    max_step_timeout_ms: int = 10000


class ArtifactProvenance(BaseModel):
    discovery_run_id: str = "disc_001"
    source_application: str = "Apex CoreBank Console v4.2"
    source_variant: str = "legacy_default"
    discovered_at: str = Field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    model: str = "gpt-4o"
    compiler_version: str = "1.2.0"


class CapabilityArtifact(BaseModel):
    schema_version: str = "1.0.0"
    capability_id: str = Field(..., description="Canonical reverse-domain identifier (e.g. corebank.member.get_balance)")
    version: str = "1.0.0"
    status: CapabilityStatus = CapabilityStatus.APPROVED
    name: str
    description: str
    application: ApplicationMetadata = Field(default_factory=ApplicationMetadata)
    entry_point: TargetEntryPoint = Field(default_factory=TargetEntryPoint)
    inputs_schema: Dict[str, InputParameter] = Field(default_factory=dict)
    outputs_schema: Dict[str, OutputField] = Field(default_factory=dict)
    preconditions: List[Precondition] = Field(default_factory=list)
    steps: List[Step] = Field(default_factory=list)
    postconditions: List[Postcondition] = Field(default_factory=list)
    policy: SafetyPolicy = Field(default_factory=SafetyPolicy)
    provenance: Optional[ArtifactProvenance] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_artifact_contract(self) -> "CapabilityArtifact":
        # 1. Schema Major Version Check
        major_ver = self.schema_version.split(".")[0]
        if major_ver != "1":
            raise ValueError(f"Incompatible schema version '{self.schema_version}'. Replay engine requires major version 1.")

        # 2. Risk vs Idempotency Guardrail
        for step in self.steps:
            if step.risk_level == RiskLevel.IRREVERSIBLE:
                if step.idempotent:
                    raise ValueError(f"Contract violation on step '{step.id}': IRREVERSIBLE step cannot be declared idempotent.")
                if step.retryable:
                    raise ValueError(f"Contract violation on step '{step.id}': IRREVERSIBLE step cannot be auto-retryable.")

        # 3. Policy & Route integrity
        if not self.entry_point.allowed_domains:
            raise ValueError("Contract violation: allowed_domains cannot be empty.")

        return self


class TenantOverride(BaseModel):
    tenant_id: str
    base_url: Optional[str] = None
    variant_id: str = "default"
    locator_overrides: Dict[str, List[LocatorCandidate]] = Field(default_factory=dict)
    custom_headers: Dict[str, str] = Field(default_factory=dict)


# --- Typed Discovery Transcript Models ---

class ObservationRecord(BaseModel):
    url: str
    title: str
    interactive_elements_count: int
    text_snippet: Optional[str] = None
    timestamp: float = Field(default_factory=time.time)


class DiscoveryActionRecord(BaseModel):
    step_index: int
    thought: str
    action: ActionType
    target_description: Optional[str] = None
    target_selector: Optional[str] = None
    selector_strategy: str = "accessibility"
    value: Optional[str] = None
    extract_fields: Optional[Dict[str, str]] = None
    is_finished: bool = False
    timestamp: float = Field(default_factory=time.time)


class DiscoveryTranscript(BaseModel):
    capability_goal: str
    entry_url: str
    application_variant: str = "default"
    model: str = "gpt-4o"
    discovery_run_id: str
    session_id: str
    observations: List[ObservationRecord] = Field(default_factory=list)
    actions: List[DiscoveryActionRecord] = Field(default_factory=list)
    extracted_outputs: Dict[str, Any] = Field(default_factory=dict)
    business_outcomes: List[Dict[str, Any]] = Field(default_factory=list)


class PolicyDecision(BaseModel):
    allowed: bool = True
    decision: Literal["ALLOW", "REQUIRE_HITL", "DENY"] = "ALLOW"
    reason: str = "Permitted by safety policy."
    matched_rule: Optional[str] = None
    risk_level: Optional[str] = None
