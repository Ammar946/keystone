"""
Playwright Surface Adapter Implementation.
Concrete implementation of SurfaceAdapter for Web and Legacy Web environments.
Handles complex DOM hierarchies, table structures, iframe contexts, accessibility trees,
DOM-level PII masking for screenshots, and live-session persistence.
"""
from typing import Dict, Any, List, Optional
import asyncio
from playwright.async_api import async_playwright, Playwright, Browser, BrowserContext, Page, Locator
from app.core.surface_adapter import SurfaceAdapter, SurfaceState, ResolvedElement


class PlaywrightSurfaceAdapter:
    """Production Web & Legacy Web Surface Adapter powered by Playwright."""

    def __init__(self):
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._session_id: str = ""
        self._headless: bool = True

    async def initialize(self, session_id: str, entry_point: str, headless: bool = True) -> None:
        self._session_id = session_id
        self._headless = headless
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self._headless,
            args=["--disable-web-security", "--no-sandbox"],
        )
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 800},
            ignore_https_errors=True,
        )
        self._page = await self._context.new_page()
        if entry_point:
            await self._page.goto(entry_point, wait_until="load")

    async def get_session_id(self) -> str:
        return self._session_id

    @property
    def page(self) -> Page:
        if not self._page:
            raise RuntimeError("SurfaceAdapter not initialized. Call initialize() first.")
        return self._page

    async def observe(self, capture_screenshot: bool = True) -> SurfaceState:
        """Capture current DOM, active route, accessibility snapshot, and visual state."""
        url = self.page.url
        title = await self.page.title()
        
        # Get page content summary
        text_content = await self.page.inner_text("body")
        
        # Extract interactive elements for discovery
        interactive_elements = await self._extract_interactive_elements()
        
        # Accessibility snapshot
        a11y_tree = {}
        try:
            a11y_tree = await self.page.accessibility.snapshot() or {}
        except Exception:
            pass

        screenshot_bytes = None
        if capture_screenshot:
            screenshot_bytes = await self.capture_screenshot(mask_sensitive=True)

        return SurfaceState(
            session_id=self._session_id,
            url_or_window=url,
            title=title,
            accessibility_tree=a11y_tree,
            viewport={"width": 1280, "height": 800},
            screenshot_bytes=screenshot_bytes,
            text_content=text_content,
            interactive_elements=interactive_elements,
        )

    async def _extract_interactive_elements(self) -> List[Dict[str, Any]]:
        """Discover buttons, inputs, links, and forms across main page and iframes."""
        js_discover = """
        () => {
            const elements = [];
            const interactive = document.querySelectorAll('button, input, select, textarea, a, form, [role="button"]');
            interactive.forEach((el, idx) => {
                const rect = el.getBoundingClientRect();
                const isVisible = (rect.width > 0 && rect.height > 0);
                if (isVisible) {
                    elements.push({
                        tag: el.tagName.toLowerCase(),
                        id: el.id || null,
                        name: el.name || null,
                        type: el.type || null,
                        role: el.getAttribute('role') || null,
                        aria_label: el.getAttribute('aria-label') || null,
                        text: (el.innerText || el.value || '').trim().substring(0, 80),
                        placeholder: el.placeholder || null,
                        bbox: { x: rect.left, y: rect.top, width: rect.width, height: rect.height }
                    });
                }
            });
            return elements;
        }
        """
        try:
            return await self.page.evaluate(js_discover)
        except Exception:
            return []

    async def resolve_target(
        self,
        target_spec: Dict[str, Any],
        timeout_ms: int = 5000,
        scope: Optional[str] = None,
        frame_context: Optional[str] = None,
    ) -> ResolvedElement:
        """
        Cascading multi-strategy locator resolution:
        1. Accessibility / Role & Name
        2. Scoped CSS
        3. Structural XPath
        4. Text / Label Matching
        5. Visual Bounding Box (Fallback)
        """
        locators_list = target_spec.get("locators", [])
        scope_str = scope or target_spec.get("scope")
        frame_str = frame_context or target_spec.get("frame_context")

        # Determine context (Main Page vs Nested Iframe)
        context_page = self.page
        if frame_str:
            # Check if frame exists by name or selector
            for f in self.page.frames:
                if frame_str in f.name or frame_str in f.url:
                    context_page = f
                    break

        last_error = None
        attempt_traces = []
        for candidate in locators_list:
            strategy = candidate.get("strategy")
            value = candidate.get("value")
            confidence = candidate.get("confidence", 0.9)

            try:
                locator: Optional[Locator] = None

                if strategy in ["accessibility", "role_and_name"]:
                    if isinstance(value, str):
                        # Format: role[name='foo'] or aria-label
                        if "[" in value and "]" in value:
                            role_part = value.split("[")[0].strip()
                            name_part = value.split("name='")[1].split("'")[0] if "name='" in value else None
                            if name_part and hasattr(context_page, "get_by_role"):
                                locator = context_page.get_by_role(role_part, name=name_part)
                            else:
                                locator = context_page.locator(value)
                        else:
                            locator = context_page.locator(f"[aria-label='{value}'], text='{value}'")

                elif strategy in ["css_scoped", "css_legacy"]:
                    if scope_str:
                        locator = context_page.locator(scope_str).locator(value)
                    else:
                        locator = context_page.locator(value)

                elif strategy in ["xpath_structural", "xpath_text"]:
                    clean_xpath = value if value.startswith("//") else (f"//{value.lstrip('./')}" if value.startswith(".") else value)
                    locator = context_page.locator(f"xpath={clean_xpath}")

                elif strategy == "text_label_relation":
                    if hasattr(context_page, "get_by_label"):
                        locator = context_page.get_by_label(value)
                    if not locator:
                        locator = context_page.locator(f"text={value}")

                elif strategy == "visual_coordinates":
                    # Coordinate fallback
                    if isinstance(value, dict) and "x" in value and "y" in value:
                        attempt_traces.append({"strategy": strategy, "value": value, "result": "found", "confidence": 0.5})
                        return ResolvedElement(
                            handle=None,
                            matched_strategy=strategy,
                            selector_value=value,
                            confidence=0.5,
                            frame_context=frame_str,
                            bounding_box=value,
                            attempt_traces=attempt_traces,
                        )

                if locator:
                    # Check visibility with per-candidate timeout
                    cand_timeout = min(timeout_ms, 1500) if len(locators_list) > 1 else timeout_ms
                    await locator.first.wait_for(state="visible", timeout=cand_timeout)
                    attempt_traces.append({"strategy": strategy, "value": value, "result": "found", "confidence": confidence})
                    return ResolvedElement(
                        handle=locator.first,
                        matched_strategy=strategy,
                        selector_value=value,
                        confidence=confidence,
                        frame_context=frame_str,
                        attempt_traces=attempt_traces,
                    )
                else:
                    attempt_traces.append({"strategy": strategy, "value": value, "result": "not_found", "error": "Locator unresolved"})

            except Exception as e:
                attempt_traces.append({"strategy": strategy, "value": value, "result": "not_found", "error": str(e)})
                last_error = e
                continue

        # If locators failed, check visual_bbox if available
        if target_spec.get("visual_bbox"):
            bbox = target_spec["visual_bbox"]
            attempt_traces.append({"strategy": "visual_coordinates", "value": bbox, "result": "found", "confidence": 0.4})
            return ResolvedElement(
                handle=None,
                matched_strategy="visual_coordinates",
                selector_value=bbox,
                confidence=0.4,
                bounding_box=bbox,
                attempt_traces=attempt_traces,
            )

        raise RuntimeError(f"Failed to resolve target '{target_spec.get('description', 'unnamed')}' with locators {locators_list}. Last error: {last_error}")

    async def click(self, element: ResolvedElement) -> None:
        if element.handle is not None:
            await element.handle.click(timeout=4000)
        elif element.bounding_box:
            # Fallback to mouse coordinate click
            x = element.bounding_box.get("x", 0)
            y = element.bounding_box.get("y", 0)
            await self.page.mouse.click(x, y)
        else:
            raise RuntimeError("ResolvedElement has neither handle nor bounding box.")

    async def type_text(
        self,
        element: ResolvedElement,
        text: str,
        clear_first: bool = True,
        sensitive: bool = False,
    ) -> None:
        if element.handle is not None:
            if clear_first:
                await element.handle.fill("", timeout=4000)
            await element.handle.fill(text, timeout=4000)
        elif element.bounding_box:
            await self.page.mouse.click(element.bounding_box["x"], element.bounding_box["y"])
            if clear_first:
                await self.page.keyboard.press("Meta+A")
                await self.page.keyboard.press("Backspace")
            await self.page.keyboard.type(text)

    async def select_option(self, element: ResolvedElement, value: str) -> None:
        if element.handle is not None:
            await element.handle.select_option(value=value)

    async def read_text(self, element: ResolvedElement) -> str:
        if element.handle is not None:
            return (await element.handle.inner_text()).strip()
        return ""

    async def read_table(self, element: ResolvedElement) -> List[Dict[str, str]]:
        """Parses an HTML table into structured rows of key-value pairs."""
        if element.handle is None:
            return []
        js_parse_table = """
        (tbl) => {
            const results = [];
            const headers = [];
            const ths = tbl.querySelectorAll('th');
            ths.forEach(th => headers.push(th.innerText.trim()));
            
            const rows = tbl.querySelectorAll('tbody tr');
            rows.forEach(tr => {
                const rowObj = {};
                const tds = tr.querySelectorAll('td');
                tds.forEach((td, idx) => {
                    const key = headers[idx] || `col_${idx}`;
                    rowObj[key] = td.innerText.trim();
                });
                if (Object.keys(rowObj).length > 0) {
                    results.push(rowObj);
                }
            });
            return results;
        }
        """
        return await element.handle.evaluate(js_parse_table)

    async def capture_screenshot(self, mask_sensitive: bool = True) -> bytes:
        """Captures page screenshot, applying DOM masking to sensitive fields."""
        if mask_sensitive:
            # Mask known sensitive classes and attributes before screenshot
            js_mask = """
            () => {
                const sens = document.querySelectorAll('#lbl_memberSsn, input[type="password"], .mask-pii');
                sens.forEach(el => {
                    el.setAttribute('data-orig-text', el.innerText);
                    el.innerText = '***-**-****';
                });
            }
            """
            try:
                await self.page.evaluate(js_mask)
            except Exception:
                pass

        screenshot_data = await self.page.screenshot(full_page=False)
        return screenshot_data

    async def wait_for_state(self, condition: str, value: Any, timeout_ms: int = 3000) -> bool:
        """Assert dynamic conditions on the live surface."""
        try:
            if condition == "route_matches":
                await self.page.wait_for_url(f"**{value}**", timeout=timeout_ms)
                return True
            elif condition == "element_present":
                locator = self.page.locator(value)
                await locator.first.wait_for(state="visible", timeout=timeout_ms)
                return True
            elif condition == "text_present":
                locator = self.page.get_by_text(value, exact=False)
                await locator.first.wait_for(state="visible", timeout=timeout_ms)
                return True
            elif condition == "element_absent":
                locator = self.page.locator(value)
                await locator.first.wait_for(state="hidden", timeout=timeout_ms)
                return True
        except Exception:
            return False
        return False

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
