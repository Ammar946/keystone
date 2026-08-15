"""
Pydantic v2 Models for Capability Artifacts, Locators, Safety Policies, and Tenant Overrides.
"""
from typing import Dict, List, Optional, Any, Union
from enum import Enum
from pydantic import BaseModel, Field


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
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TenantOverride(BaseModel):
    tenant_id: str
    base_url: Optional[str] = None
    variant_id: str = "default"
    locator_overrides: Dict[str, List[LocatorCandidate]] = Field(default_factory=dict)
    custom_headers: Dict[str, str] = Field(default_factory=dict)
