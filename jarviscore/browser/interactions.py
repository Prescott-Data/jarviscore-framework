"""
Ref-based browser interactions.
Port of OpenClaw's pw-tools-core.interactions.ts to Python.
"""
import logging
from typing import Dict, Any, Optional, List, Literal
from dataclasses import dataclass

from .session import BrowserSession

logger = logging.getLogger(__name__)


class BrowserInteractionError(Exception):
    """Error during browser interaction."""
    def __init__(self, message: str, ref: Optional[str] = None):
        self.ref = ref
        super().__init__(f"[ref={ref}] {message}" if ref else message)


def _normalize_timeout(timeout_ms: Optional[int], default: int = 8000) -> int:
    """Normalize timeout to valid range."""
    if timeout_ms is None:
        return default
    return max(500, min(60_000, timeout_ms))


def _to_friendly_error(err: Exception, ref: Optional[str] = None) -> BrowserInteractionError:
    """Convert Playwright error to user-friendly error."""
    msg = str(err)
    
    # Common error patterns
    if "Timeout" in msg:
        return BrowserInteractionError(f"Element timed out - may not be visible or interactive", ref)
    if "not visible" in msg.lower():
        return BrowserInteractionError(f"Element not visible on page", ref)
    if "not attached" in msg.lower():
        return BrowserInteractionError(f"Element no longer in DOM - page may have changed", ref)
    if "intercept" in msg.lower():
        return BrowserInteractionError(f"Click intercepted by another element", ref)
    
    return BrowserInteractionError(msg, ref)


class BrowserInteractions:
    """
    Ref-based browser interactions.
    All actions use refs from snapshot() instead of CSS selectors.
    """
    
    def __init__(self, session: BrowserSession):
        self.session = session
    
    async def click(
        self,
        ref: str,
        double_click: bool = False,
        button: Literal["left", "right", "middle"] = "left",
        modifiers: Optional[List[Literal["Alt", "Control", "Meta", "Shift"]]] = None,
        timeout_ms: Optional[int] = None
    ) -> None:
        """
        Click an element by ref.
        
        Args:
            ref: Element ref from snapshot (e.g., "e1")
            double_click: If True, double-click instead
            button: Mouse button to use
            modifiers: Keyboard modifiers to hold during click
            timeout_ms: Timeout for action
        """
        timeout = _normalize_timeout(timeout_ms)
        locator = self.session.ref_locator(ref)
        
        try:
            if double_click:
                await locator.dblclick(
                    timeout=timeout,
                    button=button,
                    modifiers=modifiers
                )
            else:
                await locator.click(
                    timeout=timeout,
                    button=button,
                    modifiers=modifiers
                )
            logger.debug(f"Clicked ref={ref}")
        except Exception as e:
            raise _to_friendly_error(e, ref)
    
    async def hover(
        self,
        ref: str,
        timeout_ms: Optional[int] = None
    ) -> None:
        """Hover over an element by ref."""
        timeout = _normalize_timeout(timeout_ms)
        locator = self.session.ref_locator(ref)
        
        try:
            await locator.hover(timeout=timeout)
            logger.debug(f"Hovered ref={ref}")
        except Exception as e:
            raise _to_friendly_error(e, ref)
    
    async def type(
        self,
        ref: str,
        text: str,
        submit: bool = False,
        slowly: bool = False,
        clear_first: bool = True,
        timeout_ms: Optional[int] = None
    ) -> None:
        """
        Type text into an element by ref.
        
        Args:
            ref: Element ref from snapshot
            text: Text to type
            submit: If True, press Enter after typing
            slowly: If True, type with delay (useful for autocomplete)
            clear_first: If True, clear existing content first (default)
            timeout_ms: Timeout for action
        """
        timeout = _normalize_timeout(timeout_ms)
        locator = self.session.ref_locator(ref)
        
        try:
            if slowly:
                # Click first, then type with delay
                await locator.click(timeout=timeout)
                if clear_first:
                    await locator.clear()
                await locator.type(text, timeout=timeout, delay=75)
            else:
                # Use fill for instant input
                await locator.fill(text, timeout=timeout)
            
            if submit:
                await locator.press("Enter", timeout=timeout)
            
            logger.debug(f"Typed into ref={ref}, submit={submit}")
        except Exception as e:
            raise _to_friendly_error(e, ref)
    
    async def select_option(
        self,
        ref: str,
        values: List[str],
        timeout_ms: Optional[int] = None
    ) -> None:
        """
        Select option(s) in a dropdown by ref.
        
        Args:
            ref: Element ref for select/combobox
            values: Option values to select
            timeout_ms: Timeout for action
        """
        if not values:
            raise BrowserInteractionError("values are required", ref)
        
        timeout = _normalize_timeout(timeout_ms)
        locator = self.session.ref_locator(ref)
        
        try:
            await locator.select_option(values, timeout=timeout)
            logger.debug(f"Selected options in ref={ref}: {values}")
        except Exception as e:
            raise _to_friendly_error(e, ref)
    
    async def check(
        self,
        ref: str,
        checked: bool = True,
        timeout_ms: Optional[int] = None
    ) -> None:
        """
        Check or uncheck a checkbox/radio by ref.
        
        Args:
            ref: Element ref for checkbox/radio
            checked: True to check, False to uncheck
            timeout_ms: Timeout for action
        """
        timeout = _normalize_timeout(timeout_ms)
        locator = self.session.ref_locator(ref)
        
        try:
            await locator.set_checked(checked, timeout=timeout)
            logger.debug(f"Set checked={checked} for ref={ref}")
        except Exception as e:
            raise _to_friendly_error(e, ref)
    
    async def drag(
        self,
        start_ref: str,
        end_ref: str,
        timeout_ms: Optional[int] = None
    ) -> None:
        """
        Drag from one element to another.
        
        Args:
            start_ref: Element ref to drag from
            end_ref: Element ref to drag to
            timeout_ms: Timeout for action
        """
        timeout = _normalize_timeout(timeout_ms)
        start_locator = self.session.ref_locator(start_ref)
        end_locator = self.session.ref_locator(end_ref)
        
        try:
            await start_locator.drag_to(end_locator, timeout=timeout)
            logger.debug(f"Dragged {start_ref} -> {end_ref}")
        except Exception as e:
            raise _to_friendly_error(e, f"{start_ref} -> {end_ref}")
    
    async def scroll_into_view(
        self,
        ref: str,
        timeout_ms: Optional[int] = None
    ) -> None:
        """Scroll element into view."""
        timeout = _normalize_timeout(timeout_ms, default=20_000)
        locator = self.session.ref_locator(ref)
        
        try:
            await locator.scroll_into_view_if_needed(timeout=timeout)
            logger.debug(f"Scrolled into view: ref={ref}")
        except Exception as e:
            raise _to_friendly_error(e, ref)
    
    async def press_key(
        self,
        key: str,
        delay_ms: int = 0
    ) -> None:
        """
        Press a keyboard key (page-level, not element-specific).
        
        Args:
            key: Key to press (e.g., "Enter", "Tab", "Escape", "ArrowDown")
            delay_ms: Delay between key down and up
        """
        if not key:
            raise BrowserInteractionError("key is required")
        
        page = self.session.page
        await page.keyboard.press(key, delay=max(0, delay_ms))
        logger.debug(f"Pressed key: {key}")
    
    async def highlight(
        self,
        ref: str
    ) -> None:
        """Highlight an element (for debugging/visual feedback)."""
        locator = self.session.ref_locator(ref)
        
        try:
            await locator.highlight()
            logger.debug(f"Highlighted ref={ref}")
        except Exception as e:
            raise _to_friendly_error(e, ref)
    
    async def get_text(
        self,
        ref: str,
        timeout_ms: Optional[int] = None
    ) -> str:
        """Get text content of an element."""
        timeout = _normalize_timeout(timeout_ms)
        locator = self.session.ref_locator(ref)
        
        try:
            text = await locator.text_content(timeout=timeout)
            return text or ""
        except Exception as e:
            raise _to_friendly_error(e, ref)
    
    async def get_attribute(
        self,
        ref: str,
        name: str,
        timeout_ms: Optional[int] = None
    ) -> Optional[str]:
        """Get an attribute value of an element."""
        timeout = _normalize_timeout(timeout_ms)
        locator = self.session.ref_locator(ref)
        
        try:
            return await locator.get_attribute(name, timeout=timeout)
        except Exception as e:
            raise _to_friendly_error(e, ref)
    
    async def is_visible(
        self,
        ref: str,
        timeout_ms: Optional[int] = None
    ) -> bool:
        """Check if element is visible."""
        try:
            locator = self.session.ref_locator(ref)
            return await locator.is_visible()
        except Exception:
            return False
    
    async def fill_form(
        self,
        fields: List[Dict[str, Any]],
        timeout_ms: Optional[int] = None
    ) -> None:
        """
        Fill multiple form fields at once.
        
        Args:
            fields: List of {"ref": "e1", "type": "text|checkbox|radio", "value": "..."}
            timeout_ms: Timeout for each field
        """
        timeout = _normalize_timeout(timeout_ms)
        
        for field in fields:
            ref = field.get("ref", "").strip()
            field_type = field.get("type", "text").strip()
            value = field.get("value")
            
            if not ref:
                continue
            
            locator = self.session.ref_locator(ref)
            
            try:
                if field_type in ("checkbox", "radio"):
                    checked = value in (True, 1, "1", "true", "True")
                    await locator.set_checked(checked, timeout=timeout)
                else:
                    # Text, email, password, etc.
                    text_value = str(value) if value is not None else ""
                    await locator.fill(text_value, timeout=timeout)
                
                logger.debug(f"Filled form field ref={ref}")
            except Exception as e:
                raise _to_friendly_error(e, ref)
    
    async def wait_for(
        self,
        time_ms: Optional[int] = None,
        text: Optional[str] = None,
        text_gone: Optional[str] = None,
        selector: Optional[str] = None,
        url: Optional[str] = None,
        load_state: Optional[Literal["load", "domcontentloaded", "networkidle"]] = None,
        timeout_ms: Optional[int] = None
    ) -> None:
        """
        Wait for various conditions.
        
        Args:
            time_ms: Wait for fixed time
            text: Wait for text to appear
            text_gone: Wait for text to disappear
            selector: Wait for selector to be visible
            url: Wait for URL pattern
            load_state: Wait for page load state
            timeout_ms: Timeout for wait conditions
        """
        page = self.session.page
        timeout = _normalize_timeout(timeout_ms, default=20_000)
        
        if time_ms is not None:
            await page.wait_for_timeout(max(0, time_ms))
        
        if text:
            await page.get_by_text(text).first.wait_for(state="visible", timeout=timeout)
        
        if text_gone:
            await page.get_by_text(text_gone).first.wait_for(state="hidden", timeout=timeout)
        
        if selector:
            await page.locator(selector).first.wait_for(state="visible", timeout=timeout)
        
        if url:
            await page.wait_for_url(url, timeout=timeout)
        
        if load_state:
            await page.wait_for_load_state(load_state, timeout=timeout)
    
    async def screenshot(
        self,
        ref: Optional[str] = None,
        full_page: bool = False,
        type: Literal["png", "jpeg"] = "png"
    ) -> bytes:
        """
        Take a screenshot.
        
        Args:
            ref: If provided, screenshot only that element
            full_page: If True, screenshot entire page (ignored if ref provided)
            type: Image format
        
        Returns:
            Screenshot bytes
        """
        page = self.session.page
        
        if ref:
            locator = self.session.ref_locator(ref)
            return await locator.screenshot(type=type)
        else:
            return await page.screenshot(type=type, full_page=full_page)
    
    async def set_input_files(
        self,
        paths: List[str],
        ref: Optional[str] = None,
        element: Optional[str] = None
    ) -> None:
        """
        Upload files via input element.
        Either ref or element selector must be provided.
        """
        if not paths:
            raise BrowserInteractionError("paths are required")
        if bool(ref) and bool(element):
            raise BrowserInteractionError("ref and element are mutually exclusive")
        if not ref and not element:
            raise BrowserInteractionError("ref or element is required")

        if ref:
            locator = self.session.ref_locator(ref)
        else:
            locator = self.session.page.locator(element).first()

        try:
            await locator.set_input_files(paths)
            # Best-effort trigger input/change events
            handle = await locator.element_handle()
            if handle:
                await handle.evaluate(
                    "el => { el.dispatchEvent(new Event('input', {bubbles: true})); "
                    "el.dispatchEvent(new Event('change', {bubbles: true})); }"
                )
        except Exception as e:
            raise _to_friendly_error(e, ref or element)

    async def download(
        self,
        ref: str,
        path: Optional[str] = None,
        timeout_ms: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Trigger a download by clicking an element and return download metadata.
        """
        timeout = _normalize_timeout(timeout_ms, default=20_000)
        locator = self.session.ref_locator(ref)
        page = self.session.page

        try:
            async with page.expect_download(timeout=timeout) as dl_info:
                await locator.click(timeout=timeout)
            download = await dl_info.value
            if path:
                await download.save_as(path)
                saved_path = path
            else:
                saved_path = await download.path()
            return {
                "url": download.url,
                "suggested_filename": download.suggested_filename,
                "path": saved_path
            }
        except Exception as e:
            raise _to_friendly_error(e, ref)

    async def cookies_get(self, url: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get cookies for the current context."""
        context = self.session.context
        try:
            if url:
                cookies = await context.cookies([url])
            else:
                cookies = await context.cookies()
            return cookies
        except Exception as e:
            raise BrowserInteractionError(str(e))

    async def cookies_set(self, cookie: Dict[str, Any]) -> None:
        """Set a cookie in the current context."""
        context = self.session.context
        try:
            await context.add_cookies([cookie])
        except Exception as e:
            raise BrowserInteractionError(str(e))

    async def cookies_clear(self) -> None:
        """Clear all cookies in the current context."""
        context = self.session.context
        try:
            await context.clear_cookies()
        except Exception as e:
            raise BrowserInteractionError(str(e))

    async def storage_get(self, kind: Literal["local", "session"], key: Optional[str] = None) -> Any:
        """Get localStorage/sessionStorage data."""
        page = self.session.page
        storage_obj = "localStorage" if kind == "local" else "sessionStorage"
        try:
            if key:
                return await page.evaluate(
                    f"(key) => {storage_obj}.getItem(key)", key
                )
            return await page.evaluate(
                f"() => Object.fromEntries(Object.entries({storage_obj}))"
            )
        except Exception as e:
            raise BrowserInteractionError(str(e))

    async def storage_set(self, kind: Literal["local", "session"], key: str, value: str) -> None:
        """Set localStorage/sessionStorage key/value."""
        page = self.session.page
        storage_obj = "localStorage" if kind == "local" else "sessionStorage"
        try:
            await page.evaluate(
                f"(key, value) => {storage_obj}.setItem(key, value)",
                key,
                value,
            )
        except Exception as e:
            raise BrowserInteractionError(str(e))

    async def storage_clear(self, kind: Literal["local", "session"]) -> None:
        """Clear localStorage/sessionStorage."""
        page = self.session.page
        storage_obj = "localStorage" if kind == "local" else "sessionStorage"
        try:
            await page.evaluate(f"() => {storage_obj}.clear()")
        except Exception as e:
            raise BrowserInteractionError(str(e))

    async def set_offline(self, offline: bool) -> None:
        """Toggle offline mode for the current context."""
        context = self.session.context
        try:
            await context.set_offline(offline)
        except Exception as e:
            raise BrowserInteractionError(str(e))

    async def pdf(self, path: Optional[str] = None) -> Dict[str, Any]:
        """Generate a PDF of the current page."""
        page = self.session.page
        try:
            data = await page.pdf()
            saved_path = None
            if path:
                with open(path, "wb") as f:
                    f.write(data)
                saved_path = path
            return {"path": saved_path, "bytes": len(data)}
        except Exception as e:
            raise BrowserInteractionError(str(e))

    async def evaluate(
        self,
        expression: str,
        ref: Optional[str] = None
    ) -> Any:
        """
        Evaluate JavaScript in browser context.
        
        Args:
            expression: JavaScript expression or function body
            ref: If provided, evaluate with element as first argument
        
        Returns:
            Result of evaluation
        """
        page = self.session.page
        
        if ref:
            locator = self.session.ref_locator(ref)
            return await locator.evaluate(expression)
        else:
            return await page.evaluate(expression)
