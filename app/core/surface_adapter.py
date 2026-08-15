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


@runtime_checkable
class SurfaceAdapter(Protocol):
    """
    Surface-neutral perception and interaction protocol.
    Concrete implementations:
      - PlaywrightSurfaceAdapter (Web / Frames / Legacy DOM)
      - DesktopSurfaceAdapter (OS Accessibility / Windows UI Automation / macOS)
      - CUASurfaceAdapter (Vision / Coordinate Model)
    """

    async def initialize(self, session_id: str, entry_point: str, headless: bool = True) -> None:
        """Initialize the live surface connection with the given session ID."""
        ...

    async def observe(self, capture_screenshot: bool = True) -> SurfaceState:
        """Extract structured multi-modal perception of the current surface state."""
        ...

    async def resolve_target(
        self,
        target_spec: Dict[str, Any],
        timeout_ms: int = 5000,
        scope: Optional[str] = None,
        frame_context: Optional[str] = None,
    ) -> ResolvedElement:
        """Resolve an element on the surface using multi-strategy cascading locators."""
        ...

    async def click(self, element: ResolvedElement) -> None:
        """Perform a single click on the resolved element."""
        ...

    async def type_text(
        self,
        element: ResolvedElement,
        text: str,
        clear_first: bool = True,
        sensitive: bool = False,
    ) -> None:
        """Type text into the resolved element."""
        ...

    async def select_option(self, element: ResolvedElement, value: str) -> None:
        """Select an option in a dropdown or select control."""
        ...

    async def read_text(self, element: ResolvedElement) -> str:
        """Read textual content from the resolved element."""
        ...

    async def read_table(self, element: ResolvedElement) -> List[Dict[str, str]]:
        """Extract structured tabular data from a legacy table or grid element."""
        ...

    async def capture_screenshot(self, mask_sensitive: bool = True) -> bytes:
        """Capture screenshot with optional DOM-level redaction of sensitive fields."""
        ...

    async def wait_for_state(self, condition: str, value: Any, timeout_ms: int = 5000) -> bool:
        """Wait for a surface condition (route_matches, element_present, text_present)."""
        ...

    async def get_session_id(self) -> str:
        """Return the unique session identifier."""
        ...

    async def close(self) -> None:
        """Cleanly close surface connection."""
        ...
