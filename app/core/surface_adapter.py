"""
Core Surface Adapter Interface & Seam.
Defines the boundary between 'how we perceive/act on a surface' and 'the recorded flow'.
Allows capability artifacts to remain surface-neutral and reusable across Web, Desktop, and CUA drivers.
"""
from typing import Protocol, Any, Dict, List, Optional, runtime_checkable
from dataclasses import dataclass, field
from enum import Enum


class RiskLevel(str, Enum):
    READ_ONLY = "READ_ONLY"
    REVERSIBLE = "REVERSIBLE"
    HIGH_RISK = "HIGH_RISK"
    IRREVERSIBLE = "IRREVERSIBLE"


class ControlOwner(str, Enum):
    AUTOMATION = "AUTOMATION"
    HUMAN = "HUMAN"


class ExecutionState(str, Enum):
    INITIALIZING = "INITIALIZING"
    RUNNING_AUTOMATION = "RUNNING_AUTOMATION"
    AWAITING_HUMAN = "AWAITING_HUMAN"
    HUMAN_CONTROL = "HUMAN_CONTROL"
    RESUMING = "RESUMING"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"
    FAILED = "FAILED"


@dataclass
class SurfaceState:
    session_id: str
    url_or_window: str
    title: str
    accessibility_tree: Dict[str, Any]
    active_frame: Optional[str] = None
    viewport: Dict[str, int] = field(default_factory=lambda: {"width": 1280, "height": 800})
    screenshot_bytes: Optional[bytes] = None
    text_content: Optional[str] = None
    interactive_elements: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ResolvedElement:
    handle: Any
    matched_strategy: str
    selector_value: Any
    confidence: float
    frame_context: Optional[str] = None
    bounding_box: Optional[Dict[str, float]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    attempt_traces: List[Dict[str, Any]] = field(default_factory=list)


@runtime_checkable
class SurfaceAdapter(Protocol):
    """
    Surface-neutral perception and action driver protocol.
    Satisfied by PlaywrightSurfaceAdapter (Web), DesktopSurfaceAdapter (Desktop OS),
    and CUASurfaceAdapter (Visual / Canvas).
    """

    async def initialize(self, session_id: str, entry_point: str, headless: bool = True) -> None:
        """Initialize driver lifecycle, navigate to target, and establish session."""
        ...

    async def get_session_id(self) -> str:
        """Return active execution session ID."""
        ...

    async def observe(self, capture_screenshot: bool = False) -> SurfaceState:
        """Capture active surface snapshot: URL, DOM/A11y tree, text, and optional screenshot."""
        ...

    async def resolve_target(
        self,
        target_spec: Dict[str, Any],
        timeout_ms: int = 5000,
        scope: Optional[str] = None,
        frame_context: Optional[str] = None,
    ) -> ResolvedElement:
        """
        Evaluate cascading multi-strategy locators:
        Accessibility -> Scoped CSS -> Structural XPath -> Coordinate Fallback.
        """
        ...

    async def click(self, target: ResolvedElement) -> None:
        """Execute atomic click on resolved target."""
        ...

    async def type_text(self, target: ResolvedElement, text: str, clear_first: bool = True) -> None:
        """Type text into resolved input element."""
        ...

    async def select_option(self, target: ResolvedElement, value: str) -> None:
        """Select option in dropdown / combobox."""
        ...

    async def read_text(self, target: ResolvedElement) -> str:
        """Extract text content from element."""
        ...

    async def read_table(self, target: ResolvedElement) -> List[Dict[str, str]]:
        """Extract structured tabular rows from table container."""
        ...

    async def capture_screenshot(self, mask_sensitive: bool = True) -> bytes:
        """Capture PNG screenshot with optional DOM-level PII masking."""
        ...

    async def wait_for_state(self, condition: str, value: Any, timeout_ms: int = 5000) -> bool:
        """Wait for dynamic state transition (element_visible, url_matches, etc.)."""
        ...

    async def close(self) -> None:
        """Cleanly terminate surface driver and close browser/window handles."""
        ...
