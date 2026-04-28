"""
High-level Browser Controller.
Unified interface for browser automation using ref-based interactions.
"""
import logging
from typing import Dict, Any, Optional, List, Literal
from dataclasses import dataclass, field
from contextlib import asynccontextmanager

from .session import BrowserSession
from .interactions import BrowserInteractions, BrowserInteractionError
from .snapshot import RoleSnapshotOptions, RoleSnapshotResult

logger = logging.getLogger(__name__)


@dataclass
class BrowserConfig:
    """Browser configuration."""
    headless: bool = True
    slow_mo: int = 0
    timeout_ms: int = 30000
    cdp_url: Optional[str] = None  # Connect to existing browser
    user_data_dir: Optional[str] = None
    launch_args: Optional[List[str]] = None
    user_agent: Optional[str] = None
    locale: Optional[str] = None
    timezone_id: Optional[str] = None
    viewport: Optional[Dict[str, int]] = None
    geolocation: Optional[Dict[str, float]] = None
    permissions: Optional[List[str]] = None
    ignore_https_errors: Optional[bool] = None
    stealth_enabled: Optional[bool] = None
    profile_name: Optional[str] = None
    profile_color: Optional[str] = None


@dataclass
class ActionResult:
    """Result of a browser action."""
    success: bool
    data: Any = None
    error: Optional[str] = None
    ref: Optional[str] = None


class BrowserController:
    """
    High-level browser controller for web automation.
    
    This is the main entry point for browser automation. It provides:
    - Navigation and page management
    - Accessibility snapshots with refs
    - Ref-based interactions (click, type, etc.)
    - Page state tracking (console, network, errors)
    
    Usage:
        async with BrowserController() as browser:
            await browser.navigate("https://example.com")
            snapshot = await browser.snapshot()
            
            # Find a button ref from snapshot
            # snapshot.refs = {"e1": RoleRef(role="button", name="Submit"), ...}
            
            await browser.click("e1")
    """
    
    def __init__(self, config: Optional[BrowserConfig] = None):
        self.config = config or BrowserConfig()
        self._session: Optional[BrowserSession] = None
        self._interactions: Optional[BrowserInteractions] = None
        self._last_snapshot: Optional[RoleSnapshotResult] = None
    
    async def connect(self) -> None:
        """Connect to browser."""
        if self._session:
            return
        
        self._session = BrowserSession(
            headless=self.config.headless,
            slow_mo=self.config.slow_mo,
            timeout_ms=self.config.timeout_ms,
            user_data_dir=self.config.user_data_dir,
            launch_args=self.config.launch_args,
            stealth_enabled=self.config.stealth_enabled,
            context_options={
                "user_agent": self.config.user_agent,
                "locale": self.config.locale,
                "timezone_id": self.config.timezone_id,
                "viewport": self.config.viewport,
                "geolocation": self.config.geolocation,
                "ignore_https_errors": self.config.ignore_https_errors,
            },
            permissions=self.config.permissions,
            profile_name=self.config.profile_name,
            profile_color=self.config.profile_color,
        )
        await self._session.connect(self.config.cdp_url)
        self._interactions = BrowserInteractions(self._session)
        
        logger.info("BrowserController connected")
    
    async def disconnect(self) -> None:
        """Disconnect from browser."""
        if self._session:
            await self._session.disconnect()
        self._session = None
        self._interactions = None
        self._last_snapshot = None
        logger.info("BrowserController disconnected")
    
    @property
    def session(self) -> BrowserSession:
        """Get browser session."""
        if not self._session:
            raise RuntimeError("Not connected. Call connect() first.")
        return self._session
    
    @property
    def interactions(self) -> BrowserInteractions:
        """Get interaction handler."""
        if not self._interactions:
            raise RuntimeError("Not connected. Call connect() first.")
        return self._interactions
    
    @property
    def last_snapshot(self) -> Optional[RoleSnapshotResult]:
        """Get last snapshot result."""
        return self._last_snapshot

    def get_active_target_id(self) -> Optional[str]:
        """Get active target id for session persistence."""
        if not self._session:
            return None
        return self._session._active_target_id()

    def is_connected(self) -> bool:
        """Return True if the underlying session is connected."""
        if not self._session:
            return False
        return bool(getattr(self._session, "_connected", False))
    
    # ==========================================================================
    # NAVIGATION
    # ==========================================================================
    
    async def navigate(self, url: str, timeout_ms: Optional[int] = None) -> ActionResult:
        """
        Navigate to URL.
        
        Returns:
            ActionResult with final URL in data
        """
        try:
            final_url = await self.session.navigate(url, timeout_ms)
            return ActionResult(success=True, data={"url": final_url})
        except Exception as e:
            logger.error(f"Navigation failed: {e}")
            return ActionResult(success=False, error=str(e))
    
    async def back(self) -> ActionResult:
        """Go back in history."""
        try:
            await self.session.page.go_back()
            return ActionResult(success=True, data={"url": self.session.page.url})
        except Exception as e:
            return ActionResult(success=False, error=str(e))
    
    async def forward(self) -> ActionResult:
        """Go forward in history."""
        try:
            await self.session.page.go_forward()
            return ActionResult(success=True, data={"url": self.session.page.url})
        except Exception as e:
            return ActionResult(success=False, error=str(e))
    
    async def reload(self) -> ActionResult:
        """Reload current page."""
        try:
            await self.session.page.reload()
            return ActionResult(success=True, data={"url": self.session.page.url})
        except Exception as e:
            return ActionResult(success=False, error=str(e))
    
    # ==========================================================================
    # SNAPSHOTS
    # ==========================================================================
    
    async def snapshot(
        self,
        interactive_only: bool = False,
        compact: bool = True,
        max_name_length: Optional[int] = None,
    ) -> ActionResult:
        """
        Take accessibility snapshot of current page.
        
        Args:
            interactive_only: Only return interactive elements
            compact: Remove empty structural elements
            max_name_length: Truncate element display names beyond this length
        
        Returns:
            ActionResult with snapshot string and refs dict
        """
        try:
            options = RoleSnapshotOptions(
                interactive_only=interactive_only,
                compact=compact,
                max_name_length=max_name_length,
            )
            result = await self.session.snapshot(options)
            self._last_snapshot = result
            
            return ActionResult(
                success=True,
                data={
                    "snapshot": result.snapshot,
                    "refs": {k: {"role": v.role, "name": v.name} for k, v in result.refs.items()},
                    "stats": result.stats
                }
            )
        except Exception as e:
            logger.error(f"Snapshot failed: {e}")
            return ActionResult(success=False, error=str(e))

    async def snapshot_ai(
        self,
        interactive_only: bool = False,
        compact: bool = True,
        max_chars: Optional[int] = None
    ) -> ActionResult:
        """
        Take an AI snapshot (if supported by Playwright).
        """
        try:
            options = RoleSnapshotOptions(
                interactive_only=interactive_only,
                compact=compact
            )
            result = await self.session.snapshot_ai(options, max_chars=max_chars)
            self._last_snapshot = result
            return ActionResult(
                success=True,
                data={
                    "snapshot": result.snapshot,
                    "refs": {k: {"role": v.role, "name": v.name} for k, v in result.refs.items()},
                    "stats": result.stats
                }
            )
        except Exception as e:
            logger.error(f"AI snapshot failed: {e}")
            return ActionResult(success=False, error=str(e))
    
    # ==========================================================================
    # INTERACTIONS (Ref-based)
    # ==========================================================================
    
    async def click(
        self,
        ref: str,
        double_click: bool = False,
        button: Literal["left", "right", "middle"] = "left",
        timeout_ms: Optional[int] = None
    ) -> ActionResult:
        """Click element by ref."""
        try:
            await self.interactions.click(ref, double_click=double_click, button=button, timeout_ms=timeout_ms)
            return ActionResult(success=True, ref=ref)
        except BrowserInteractionError as e:
            return ActionResult(success=False, error=str(e), ref=e.ref)
        except Exception as e:
            return ActionResult(success=False, error=str(e), ref=ref)
    
    async def type(
        self,
        ref: str,
        text: str,
        submit: bool = False,
        slowly: bool = False,
        timeout_ms: Optional[int] = None
    ) -> ActionResult:
        """Type text into element by ref."""
        try:
            await self.interactions.type(ref, text, submit=submit, slowly=slowly, timeout_ms=timeout_ms)
            return ActionResult(success=True, ref=ref, data={"typed": text})
        except BrowserInteractionError as e:
            return ActionResult(success=False, error=str(e), ref=e.ref)
        except Exception as e:
            return ActionResult(success=False, error=str(e), ref=ref)
    
    async def select(
        self,
        ref: str,
        values: List[str],
        timeout_ms: Optional[int] = None
    ) -> ActionResult:
        """Select option(s) from dropdown by ref."""
        try:
            await self.interactions.select_option(ref, values, timeout_ms=timeout_ms)
            return ActionResult(success=True, ref=ref, data={"selected": values})
        except BrowserInteractionError as e:
            return ActionResult(success=False, error=str(e), ref=e.ref)
        except Exception as e:
            return ActionResult(success=False, error=str(e), ref=ref)
    
    async def check(
        self,
        ref: str,
        checked: bool = True,
        timeout_ms: Optional[int] = None
    ) -> ActionResult:
        """Check/uncheck checkbox or radio by ref."""
        try:
            await self.interactions.check(ref, checked, timeout_ms=timeout_ms)
            return ActionResult(success=True, ref=ref, data={"checked": checked})
        except BrowserInteractionError as e:
            return ActionResult(success=False, error=str(e), ref=e.ref)
        except Exception as e:
            return ActionResult(success=False, error=str(e), ref=ref)
    
    async def hover(
        self,
        ref: str,
        timeout_ms: Optional[int] = None
    ) -> ActionResult:
        """Hover over element by ref."""
        try:
            await self.interactions.hover(ref, timeout_ms=timeout_ms)
            return ActionResult(success=True, ref=ref)
        except BrowserInteractionError as e:
            return ActionResult(success=False, error=str(e), ref=e.ref)
        except Exception as e:
            return ActionResult(success=False, error=str(e), ref=ref)
    
    async def drag(
        self,
        start_ref: str,
        end_ref: str,
        timeout_ms: Optional[int] = None
    ) -> ActionResult:
        """Drag from one element to another."""
        try:
            await self.interactions.drag(start_ref, end_ref, timeout_ms=timeout_ms)
            return ActionResult(success=True, data={"from": start_ref, "to": end_ref})
        except BrowserInteractionError as e:
            return ActionResult(success=False, error=str(e), ref=e.ref)
        except Exception as e:
            return ActionResult(success=False, error=str(e))
    
    async def scroll_to(
        self,
        ref: str,
        timeout_ms: Optional[int] = None
    ) -> ActionResult:
        """Scroll element into view."""
        try:
            await self.interactions.scroll_into_view(ref, timeout_ms=timeout_ms)
            return ActionResult(success=True, ref=ref)
        except BrowserInteractionError as e:
            return ActionResult(success=False, error=str(e), ref=e.ref)
        except Exception as e:
            return ActionResult(success=False, error=str(e), ref=ref)
    
    async def press_key(
        self,
        key: str,
        delay_ms: int = 0
    ) -> ActionResult:
        """Press keyboard key."""
        try:
            await self.interactions.press_key(key, delay_ms=delay_ms)
            return ActionResult(success=True, data={"key": key})
        except Exception as e:
            return ActionResult(success=False, error=str(e))
    
    async def get_text(
        self,
        ref: str,
        timeout_ms: Optional[int] = None
    ) -> ActionResult:
        """Get text content of element."""
        try:
            text = await self.interactions.get_text(ref, timeout_ms=timeout_ms)
            return ActionResult(success=True, ref=ref, data={"text": text})
        except BrowserInteractionError as e:
            return ActionResult(success=False, error=str(e), ref=e.ref)
        except Exception as e:
            return ActionResult(success=False, error=str(e), ref=ref)
    
    async def fill_form(
        self,
        fields: List[Dict[str, Any]],
        timeout_ms: Optional[int] = None
    ) -> ActionResult:
        """Fill multiple form fields."""
        try:
            await self.interactions.fill_form(fields, timeout_ms=timeout_ms)
            return ActionResult(success=True, data={"fields_filled": len(fields)})
        except BrowserInteractionError as e:
            return ActionResult(success=False, error=str(e), ref=e.ref)
        except Exception as e:
            return ActionResult(success=False, error=str(e))
    
    # ==========================================================================
    # WAITS
    # ==========================================================================
    
    async def wait(
        self,
        time_ms: Optional[int] = None,
        text: Optional[str] = None,
        text_gone: Optional[str] = None,
        url: Optional[str] = None,
        load_state: Optional[Literal["load", "domcontentloaded", "networkidle"]] = None,
        timeout_ms: Optional[int] = None
    ) -> ActionResult:
        """Wait for various conditions."""
        try:
            await self.interactions.wait_for(
                time_ms=time_ms,
                text=text,
                text_gone=text_gone,
                url=url,
                load_state=load_state,
                timeout_ms=timeout_ms
            )
            return ActionResult(success=True)
        except Exception as e:
            return ActionResult(success=False, error=str(e))
    
    # ==========================================================================
    # SCREENSHOTS
    # ==========================================================================
    
    async def screenshot(
        self,
        ref: Optional[str] = None,
        full_page: bool = False,
        format: Literal["png", "jpeg"] = "png"
    ) -> ActionResult:
        """
        Take screenshot.
        
        Returns:
            ActionResult with screenshot bytes in data
        """
        try:
            screenshot_bytes = await self.interactions.screenshot(ref=ref, full_page=full_page, type=format)
            return ActionResult(success=True, data={"bytes": screenshot_bytes, "format": format}, ref=ref)
        except BrowserInteractionError as e:
            return ActionResult(success=False, error=str(e), ref=e.ref)
        except Exception as e:
            return ActionResult(success=False, error=str(e), ref=ref)
    
    async def upload_files(
        self,
        paths: List[str],
        ref: Optional[str] = None,
        element: Optional[str] = None
    ) -> ActionResult:
        """
        Upload files via input element.
        """
        try:
            await self.interactions.set_input_files(paths=paths, ref=ref, element=element)
            return ActionResult(success=True, data={"paths": paths}, ref=ref)
        except BrowserInteractionError as e:
            return ActionResult(success=False, error=str(e), ref=e.ref)
        except Exception as e:
            return ActionResult(success=False, error=str(e), ref=ref)

    async def download(
        self,
        ref: str,
        path: Optional[str] = None,
        timeout_ms: Optional[int] = None
    ) -> ActionResult:
        """
        Trigger a download and return metadata.
        """
        try:
            info = await self.interactions.download(ref=ref, path=path, timeout_ms=timeout_ms)
            return ActionResult(success=True, data=info, ref=ref)
        except BrowserInteractionError as e:
            return ActionResult(success=False, error=str(e), ref=e.ref)
        except Exception as e:
            return ActionResult(success=False, error=str(e), ref=ref)

    async def cookies_get(self, url: Optional[str] = None) -> ActionResult:
        """Get cookies for current context."""
        try:
            cookies = await self.interactions.cookies_get(url=url)
            return ActionResult(success=True, data={"cookies": cookies})
        except BrowserInteractionError as e:
            return ActionResult(success=False, error=str(e))
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    async def cookies_set(self, cookie: Dict[str, Any]) -> ActionResult:
        """Set a cookie in the current context."""
        try:
            await self.interactions.cookies_set(cookie)
            return ActionResult(success=True, data={"cookie": cookie})
        except BrowserInteractionError as e:
            return ActionResult(success=False, error=str(e))
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    async def cookies_clear(self) -> ActionResult:
        """Clear cookies in the current context."""
        try:
            await self.interactions.cookies_clear()
            return ActionResult(success=True, data={"cleared": True})
        except BrowserInteractionError as e:
            return ActionResult(success=False, error=str(e))
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    async def storage_get(self, kind: str, key: Optional[str] = None) -> ActionResult:
        """Get local/session storage data."""
        try:
            if kind not in ("local", "session"):
                return ActionResult(success=False, error="kind must be local|session")
            data = await self.interactions.storage_get(kind=kind, key=key)
            return ActionResult(success=True, data={"kind": kind, "key": key, "value": data})
        except BrowserInteractionError as e:
            return ActionResult(success=False, error=str(e))
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    async def storage_set(self, kind: str, key: str, value: str) -> ActionResult:
        """Set local/session storage key/value."""
        try:
            if kind not in ("local", "session"):
                return ActionResult(success=False, error="kind must be local|session")
            await self.interactions.storage_set(kind=kind, key=key, value=value)
            return ActionResult(success=True, data={"kind": kind, "key": key})
        except BrowserInteractionError as e:
            return ActionResult(success=False, error=str(e))
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    async def storage_clear(self, kind: str) -> ActionResult:
        """Clear local/session storage."""
        try:
            if kind not in ("local", "session"):
                return ActionResult(success=False, error="kind must be local|session")
            await self.interactions.storage_clear(kind=kind)
            return ActionResult(success=True, data={"kind": kind, "cleared": True})
        except BrowserInteractionError as e:
            return ActionResult(success=False, error=str(e))
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    async def set_offline(self, offline: bool) -> ActionResult:
        """Toggle offline mode."""
        try:
            await self.interactions.set_offline(offline)
            return ActionResult(success=True, data={"offline": offline})
        except BrowserInteractionError as e:
            return ActionResult(success=False, error=str(e))
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    async def pdf(self, path: Optional[str] = None) -> ActionResult:
        """Generate a PDF of the current page."""
        try:
            info = await self.interactions.pdf(path=path)
            return ActionResult(success=True, data=info)
        except BrowserInteractionError as e:
            return ActionResult(success=False, error=str(e))
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    # ==========================================================================
    # PAGE INFO
    # ==========================================================================
    
    async def get_page_info(self) -> ActionResult:
        """Get current page info (URL, title, viewport)."""
        try:
            info = await self.session.get_page_info()
            return ActionResult(success=True, data=info)
        except Exception as e:
            return ActionResult(success=False, error=str(e))
    
    async def get_console(self, limit: int = 50) -> ActionResult:
        """Get recent console messages."""
        try:
            messages = await self.session.get_console_messages(limit)
            return ActionResult(success=True, data={"messages": messages, "count": len(messages)})
        except Exception as e:
            return ActionResult(success=False, error=str(e))
    
    async def get_network(self, limit: int = 50) -> ActionResult:
        """Get recent network requests."""
        try:
            requests = await self.session.get_network_requests(limit)
            return ActionResult(success=True, data={"requests": requests, "count": len(requests)})
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    # ==========================================================================
    # NETWORK CAPTURE
    # ==========================================================================

    async def capture_start(self, session_id: Optional[str] = None) -> ActionResult:
        try:
            result = self.session.start_capture(session_id=session_id)
            return ActionResult(success=bool(result.get("enabled", False)), data=result)
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    async def capture_stop(self, persist: bool = True) -> ActionResult:
        try:
            result = self.session.stop_capture(persist=persist)
            return ActionResult(success=bool(result.get("enabled", True)), data=result)
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    async def capture_status(self) -> ActionResult:
        try:
            result = self.session.capture_status()
            return ActionResult(success=bool(result.get("enabled", False)), data=result)
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    async def capture_export(self, min_confidence: int = 40) -> ActionResult:
        try:
            result = self.session.export_capture(min_confidence=min_confidence)
            return ActionResult(success=bool(result.get("enabled", False)), data=result)
        except Exception as e:
            return ActionResult(success=False, error=str(e))
    
    # ==========================================================================
    # JAVASCRIPT
    # ==========================================================================
    
    async def evaluate(
        self,
        expression: str,
        ref: Optional[str] = None
    ) -> ActionResult:
        """
        Evaluate JavaScript.
        
        Args:
            expression: JS expression or function body
            ref: If provided, element is passed as first argument
        """
        try:
            result = await self.interactions.evaluate(expression, ref=ref)
            return ActionResult(success=True, data={"result": result}, ref=ref)
        except BrowserInteractionError as e:
            return ActionResult(success=False, error=str(e), ref=e.ref)
        except Exception as e:
            return ActionResult(success=False, error=str(e), ref=ref)
    
    # ==========================================================================
    # CONTEXT MANAGERS
    # ==========================================================================
    
    async def __aenter__(self):
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()


@asynccontextmanager
async def browser_controller(
    headless: bool = True,
    slow_mo: int = 0,
    timeout_ms: int = 30000,
    cdp_url: Optional[str] = None
):
    """
    Context manager for browser controller.
    
    Usage:
        async with browser_controller() as browser:
            await browser.navigate("https://example.com")
            result = await browser.snapshot()
            await browser.click("e1")
    """
    config = BrowserConfig(
        headless=headless,
        slow_mo=slow_mo,
        timeout_ms=timeout_ms,
        cdp_url=cdp_url
    )
    controller = BrowserController(config)
    try:
        await controller.connect()
        yield controller
    finally:
        await controller.disconnect()
