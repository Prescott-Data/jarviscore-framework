"""
Browser session management using Playwright.
Port of OpenClaw's pw-session.ts to Python.
"""
import asyncio
import json
import logging
import urllib.parse
import urllib.request
from datetime import datetime
from dataclasses import dataclass, field
from typing import Dict, Optional, List, Any, Callable, Awaitable, Tuple
from contextlib import asynccontextmanager

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    Playwright,
    Locator,
    Error as PlaywrightError
)

try:
    from playwright_stealth import Stealth
except Exception:  # pragma: no cover - optional dependency
    Stealth = None

from .snapshot import (
    RoleRef,
    RoleSnapshotOptions,
    RoleSnapshotResult,
    build_role_snapshot_from_aria,
    build_role_snapshot_from_ai,
)
from .capture import BrowserTrafficCapture, build_capture_config, should_capture_body

logger = logging.getLogger(__name__)


@dataclass
class _CdpConnection:
    playwright: Playwright
    browser: Browser
    refcount: int = 0


_cdp_cache: Dict[str, _CdpConnection] = {}
_cdp_connecting: Dict[str, asyncio.Task] = {}
_role_refs_by_target: Dict[str, Dict[str, RoleRef]] = {}
_role_refs_frame_by_target: Dict[str, Optional[str]] = {}


@dataclass
class ConsoleMessage:
    """Browser console message."""
    type: str
    text: str
    timestamp: str
    url: Optional[str] = None
    line_number: Optional[int] = None


@dataclass
class PageError:
    """Browser page error."""
    message: str
    name: Optional[str] = None
    stack: Optional[str] = None
    timestamp: str = ""


@dataclass 
class NetworkRequest:
    """Browser network request."""
    id: str
    timestamp: str
    method: str
    url: str
    resource_type: Optional[str] = None
    status: Optional[int] = None
    ok: Optional[bool] = None
    failure_text: Optional[str] = None


@dataclass
class PageState:
    """State tracked per page."""
    console_messages: List[ConsoleMessage] = field(default_factory=list)
    errors: List[PageError] = field(default_factory=list)
    requests: List[NetworkRequest] = field(default_factory=list)
    next_request_id: int = 0
    
    # Role refs from last snapshot
    role_refs: Dict[str, RoleRef] = field(default_factory=dict)
    role_refs_frame_selector: Optional[str] = None
    
    # Limits
    MAX_CONSOLE = 500
    MAX_ERRORS = 200
    MAX_REQUESTS = 500
    
    def add_console(self, msg: ConsoleMessage) -> None:
        self.console_messages.append(msg)
        if len(self.console_messages) > self.MAX_CONSOLE:
            self.console_messages.pop(0)
    
    def add_error(self, err: PageError) -> None:
        self.errors.append(err)
        if len(self.errors) > self.MAX_ERRORS:
            self.errors.pop(0)
    
    def add_request(self, req: NetworkRequest) -> None:
        self.requests.append(req)
        if len(self.requests) > self.MAX_REQUESTS:
            self.requests.pop(0)
    
    def get_next_request_id(self) -> str:
        self.next_request_id += 1
        return f"r{self.next_request_id}"


class BrowserSession:
    """
    Manages a browser session using Playwright.
    Handles connection, page state, and ref-based element location.
    """
    
    def __init__(
        self,
        headless: bool = True,
        slow_mo: int = 0,
        timeout_ms: int = 30000,
        user_data_dir: Optional[str] = None,
        launch_args: Optional[List[str]] = None,
        stealth_enabled: Optional[bool] = None,
        context_options: Optional[Dict[str, Any]] = None,
        permissions: Optional[List[str]] = None,
        profile_name: Optional[str] = None,
        profile_color: Optional[str] = None,
    ):
        self.headless = headless
        self.slow_mo = slow_mo
        self.timeout_ms = timeout_ms
        self.user_data_dir = user_data_dir
        self.launch_args = launch_args or []
        self.stealth_enabled = bool(stealth_enabled) if stealth_enabled is not None else False
        self.context_options = context_options or {}
        self.permissions = permissions or []
        self.profile_name = profile_name
        self.profile_color = profile_color
        
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._page_states: Dict[Page, PageState] = {}
        self._targets: Dict[str, Page] = {}
        self._target_counter = 0
        self._last_target_id: Optional[str] = None
        self._connected = False
        self._cdp_url: Optional[str] = None
        self._cdp_shared = False
        self._capture: Optional[BrowserTrafficCapture] = None
        self._last_capture: Optional[BrowserTrafficCapture] = None
        self._capture_config = build_capture_config()
        self._stealth_warned = False

    def _new_target_id(self) -> str:
        self._target_counter += 1
        return f"t{self._target_counter}"

    def _register_page(self, page: Page, target_id: Optional[str] = None) -> str:
        if not target_id:
            target_id = self._new_target_id()
        if page not in self._page_states:
            self._setup_page_listeners(page)
        self._targets[target_id] = page
        self._last_target_id = target_id
        if not self._page:
            self._page = page
        return target_id

    async def _register_page_async(self, page: Page, target_id: Optional[str] = None) -> str:
        if not target_id:
            target_id = await self._get_cdp_target_id(page) or self._new_target_id()
        return self._register_page(page, target_id=target_id)

    async def _apply_stealth(self, page: Page) -> None:
        if not self.stealth_enabled:
            return
        if Stealth is None:
            if not self._stealth_warned:
                logger.warning("playwright-stealth not installed; skipping stealth profile")
                self._stealth_warned = True
            return
        try:
            stealth = Stealth()
            await stealth.apply_stealth_async(page)
        except Exception as exc:
            logger.warning(f"Failed to apply stealth profile: {exc}")

    def _role_refs_key(self, target_id: str) -> Optional[str]:
        if not self._cdp_url or not target_id:
            return None
        return f"{self._cdp_url}::{target_id}"

    def _cache_role_refs(self, target_id: str, refs: Dict[str, RoleRef], frame_selector: Optional[str]) -> None:
        key = self._role_refs_key(target_id)
        if not key:
            return
        _role_refs_by_target[key] = dict(refs)
        _role_refs_frame_by_target[key] = frame_selector

    def _restore_role_refs(self, target_id: str) -> None:
        key = self._role_refs_key(target_id)
        if not key:
            return
        cached = _role_refs_by_target.get(key)
        if not cached:
            return
        state = self._get_or_create_page_state(self.page)
        if state.role_refs:
            return
        state.role_refs = dict(cached)
        state.role_refs_frame_selector = _role_refs_frame_by_target.get(key)

    async def _get_cdp_target_id(self, page: Page) -> Optional[str]:
        try:
            session = await page.context.new_cdp_session(page)
            info = await session.send("Target.getTargetInfo")
            target_info = info.get("targetInfo") if isinstance(info, dict) else None
            target_id = target_info.get("targetId") if isinstance(target_info, dict) else None
            return str(target_id) if target_id else None
        except Exception:
            return None
        finally:
            try:
                await session.detach()
            except Exception:
                pass

    async def _list_cdp_targets(self) -> List[Dict[str, Any]]:
        if not self._cdp_url:
            return []
        try:
            base = self._cdp_http_url(self._cdp_url)
            data = await self._fetch_json(f"{base}/json/list", timeout_ms=1500)
            if isinstance(data, list):
                return [t for t in data if isinstance(t, dict)]
        except Exception:
            return []
        return []

    async def _resolve_page_by_target_id(self, target_id: str) -> Optional[Page]:
        if not self._context:
            return None
        pages = list(self._context.pages)
        # Strategy 1: CDP session -> targetId match
        for page in pages:
            candidate_id = await self._get_cdp_target_id(page)
            if candidate_id and candidate_id == target_id:
                await self._register_page_async(page, target_id=candidate_id)
                return page

        # Strategy 2: /json/list targetId -> URL match
        targets = await self._list_cdp_targets()
        target = next((t for t in targets if str(t.get("id", "")) == target_id), None)
        if target:
            target_url = str(target.get("url", ""))
            if target_url:
                url_matches = [p for p in pages if p.url == target_url]
                if len(url_matches) == 1:
                    await self._register_page_async(url_matches[0], target_id=target_id)
                    return url_matches[0]
                # Strategy 3: index-based fallback when multiple URL matches
                if len(url_matches) > 1:
                    same_url_targets = [t for t in targets if str(t.get("url", "")) == target_url]
                    if len(same_url_targets) == len(url_matches):
                        idx = next((i for i, t in enumerate(same_url_targets) if str(t.get("id", "")) == target_id), -1)
                        if 0 <= idx < len(url_matches):
                            await self._register_page_async(url_matches[idx], target_id=target_id)
                            return url_matches[idx]

        # Strategy 4: if only one page exists, return it
        if len(pages) == 1:
            await self._register_page_async(pages[0], target_id=target_id)
            return pages[0]
        return None

    def _normalize_cdp_url(self, raw: str) -> str:
        return raw.rstrip("/")

    def _cdp_http_url(self, cdp_url: str) -> str:
        parsed = urllib.parse.urlparse(cdp_url)
        scheme = "http" if parsed.scheme in ("ws", "wss") else parsed.scheme or "http"
        netloc = parsed.netloc or parsed.path
        base = f"{scheme}://{netloc}"
        return base.rstrip("/")

    async def _fetch_json(self, url: str, timeout_ms: int = 1500) -> Dict[str, Any]:
        def _blocking_fetch() -> Dict[str, Any]:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=timeout_ms / 1000) as resp:
                return json.loads(resp.read().decode("utf-8"))

        return await asyncio.to_thread(_blocking_fetch)

    async def _is_cdp_http_reachable(self, cdp_url: str, timeout_ms: int = 1500) -> bool:
        try:
            base = self._cdp_http_url(cdp_url)
            await self._fetch_json(f"{base}/json/version", timeout_ms=timeout_ms)
            return True
        except Exception:
            return False

    async def _connect_cdp_shared(self, cdp_url: str) -> _CdpConnection:
        normalized = self._normalize_cdp_url(cdp_url)
        cached = _cdp_cache.get(normalized)
        if cached and cached.browser and cached.browser.is_connected():
            cached.refcount += 1
            return cached
        if cached:
            _cdp_cache.pop(normalized, None)

        pending = _cdp_connecting.get(normalized)
        if pending:
            return await pending

        async def _do_connect() -> _CdpConnection:
            last_err: Optional[Exception] = None
            for attempt in range(3):
                try:
                    timeout = 5000 + attempt * 2000
                    pw = await async_playwright().start()
                    browser = await pw.chromium.connect_over_cdp(normalized, timeout=timeout)
                    conn = _CdpConnection(playwright=pw, browser=browser, refcount=1)
                    _cdp_cache[normalized] = conn
                    browser.on("disconnected", lambda: _cdp_cache.pop(normalized, None))
                    return conn
                except Exception as exc:
                    last_err = exc
                    await asyncio.sleep(0.25 + attempt * 0.25)
            raise last_err or RuntimeError("Failed to connect to CDP")

        task = asyncio.create_task(_do_connect())
        _cdp_connecting[normalized] = task
        try:
            return await task
        finally:
            _cdp_connecting.pop(normalized, None)

    def _active_target_id(self) -> Optional[str]:
        if self._page:
            for target_id, page in self._targets.items():
                if page == self._page:
                    return target_id
        return self._last_target_id

    def _get_target_id_for_page(self, page: Page) -> Optional[str]:
        for target_id, target_page in self._targets.items():
            if target_page == page:
                return target_id
        return None
    
    async def connect(self, cdp_url: Optional[str] = None) -> None:
        """
        Connect to browser. 
        If cdp_url provided, connects to existing browser via CDP.
        Otherwise launches a new browser.
        """
        if self._connected:
            return
        
        self._cdp_url = self._normalize_cdp_url(cdp_url) if cdp_url else None
        
        context_options = {k: v for k, v in self.context_options.items() if v is not None}

        if cdp_url:
            # Connect to existing browser via CDP
            logger.info(f"Connecting to browser via CDP: {cdp_url}")
            conn = await self._connect_cdp_shared(cdp_url)
            self._playwright = conn.playwright
            self._browser = conn.browser
            self._cdp_shared = True
            # Get existing context and page
            contexts = self._browser.contexts
            if contexts and not context_options:
                self._context = contexts[0]
                pages = self._context.pages
                if pages:
                    for page in pages:
                        await self._register_page_async(page)
                        await self._apply_stealth(page)
            else:
                self._context = await self._browser.new_context(**context_options)
            if self.permissions:
                await self._context.grant_permissions(self.permissions)
        else:
            # Launch new browser
            logger.info(f"Launching new browser (headless={self.headless})")
            self._playwright = await async_playwright().start()
            launch_args = list(self.launch_args or [])
            if self.headless and not any("headless" in arg for arg in launch_args):
                launch_args.extend(["--headless=new", "--disable-gpu"])

            if self.user_data_dir:
                from .profile_decoration import decorate_profile

                decorate_profile(self.user_data_dir, self.profile_name, self.profile_color)
                self._context = await self._playwright.chromium.launch_persistent_context(
                    self.user_data_dir,
                    headless=self.headless,
                    slow_mo=self.slow_mo,
                    args=launch_args,
                    **context_options,
                )
                self._browser = self._context.browser
            else:
                self._browser = await self._playwright.chromium.launch(
                    headless=self.headless,
                    slow_mo=self.slow_mo,
                    args=launch_args,
                )
                self._context = await self._browser.new_context(**context_options)

            if self.permissions:
                await self._context.grant_permissions(self.permissions)

            pages = self._context.pages
            if pages:
                for page in pages:
                    await self._register_page_async(page)
                    await self._apply_stealth(page)
            else:
                page = await self._context.new_page()
                await self._register_page_async(page)
                await self._apply_stealth(page)
        
        self._connected = True
        logger.info("Browser session connected")
    
    async def disconnect(self) -> None:
        """Disconnect from browser."""
        if not self._connected:
            return
        
        try:
            if self._context and not self._cdp_shared:
                await self._context.close()
            if self._browser and not self._cdp_shared:
                await self._browser.close()
        except Exception as e:
            logger.warning(f"Error closing browser: {e}")
        
        try:
            if self._playwright and not self._cdp_shared:
                await self._playwright.stop()
        except Exception as e:
            logger.warning(f"Error stopping playwright: {e}")

        if self._cdp_shared and self._cdp_url:
            cached = _cdp_cache.get(self._cdp_url)
            if cached:
                cached.refcount = max(0, cached.refcount - 1)
                if cached.refcount == 0:
                    try:
                        await cached.browser.close()
                    except Exception:
                        pass
                    try:
                        await cached.playwright.stop()
                    except Exception:
                        pass
                    _cdp_cache.pop(self._cdp_url, None)
        
        self._browser = None
        self._context = None
        self._page = None
        self._playwright = None
        self._page_states.clear()
        self._targets.clear()
        self._target_counter = 0
        self._last_target_id = None
        self._connected = False
        self._cdp_shared = False
        self._cdp_url = None
        logger.info("Browser session disconnected")

    async def ensure_page(self, target_id: Optional[str] = None) -> Page:
        if not self._connected or not self._context:
            raise RuntimeError("Browser session not connected")
        if target_id and target_id in self._targets:
            return self._targets[target_id]
        if target_id:
            resolved = await self._resolve_page_by_target_id(target_id)
            if resolved:
                return resolved
            page = await self._context.new_page()
            await self._register_page_async(page, target_id=target_id)
            await self._apply_stealth(page)
            return page
        if self._page:
            return self._page
        if self._targets:
            page = next(iter(self._targets.values()))
            self._page = page
            return page
        page = await self._context.new_page()
        await self._register_page_async(page)
        await self._apply_stealth(page)
        return page

    async def set_active_target(self, target_id: Optional[str]) -> Optional[str]:
        page = await self.ensure_page(target_id)
        self._page = page
        if target_id:
            self._restore_role_refs(target_id)
        return self._active_target_id()

    async def list_tabs(self) -> List[Dict[str, Any]]:
        tabs: List[Dict[str, Any]] = []
        for target_id, page in self._targets.items():
            title = ""
            try:
                title = await page.title()
            except Exception:
                title = ""
            tabs.append(
                {
                    "target_id": target_id,
                    "url": page.url,
                    "title": title,
                }
            )
        return tabs
    
    def _setup_page_listeners(self, page: Page) -> None:
        """Set up event listeners on a page."""
        state = self._get_or_create_page_state(page)
        
        def on_console(msg):
            state.add_console(ConsoleMessage(
                type=msg.type,
                text=msg.text,
                timestamp=datetime.now().isoformat(),
                url=msg.location.get("url") if msg.location else None,
                line_number=msg.location.get("lineNumber") if msg.location else None
            ))
        
        def on_page_error(err):
            state.add_error(PageError(
                message=str(err),
                timestamp=datetime.now().isoformat()
            ))
        
        def on_request(req):
            req_id = state.get_next_request_id()
            state.add_request(NetworkRequest(
                id=req_id,
                timestamp=datetime.now().isoformat(),
                method=req.method,
                url=req.url,
                resource_type=req.resource_type
            ))
            # Store mapping for response handling
            req._custom_id = req_id  # type: ignore
            self._record_capture_request(page, req, req_id)
        
        def on_response(resp):
            req = resp.request
            req_id = getattr(req, '_custom_id', None)
            if not req_id:
                return
            # Find and update the request
            for r in reversed(state.requests):
                if r.id == req_id:
                    r.status = resp.status
                    r.ok = resp.ok
                    break
            asyncio.create_task(self._record_capture_response(resp, req_id))
        
        def on_request_failed(req):
            req_id = getattr(req, '_custom_id', None)
            if not req_id:
                return
            for r in reversed(state.requests):
                if r.id == req_id:
                    r.failure_text = req.failure
                    r.ok = False
                    break
            self._record_capture_failure(req_id, req.failure)
        
        page.on("console", on_console)
        page.on("pageerror", on_page_error)
        page.on("request", on_request)
        page.on("response", on_response)
        page.on("requestfailed", on_request_failed)
        
        def on_close():
            self._page_states.pop(page, None)
            for target_id, target_page in list(self._targets.items()):
                if target_page == page:
                    self._targets.pop(target_id, None)
                    if self._page == page:
                        self._page = None
                    break
        page.on("close", on_close)

    def _record_capture_request(self, page: Page, req: Any, req_id: str) -> None:
        if not self._capture or not self._capture.config.enabled:
            return
        try:
            body = req.post_data or None
        except Exception:
            body = None
        self._capture.add_request(
            request_id=req_id,
            method=req.method,
            url=req.url,
            headers=req.headers or {},
            body=body,
            resource_type=req.resource_type,
            profile=self.profile_name,
            target_id=self._get_target_id_for_page(page),
        )

    async def _record_capture_response(self, resp: Any, req_id: str) -> None:
        if not self._capture or not self._capture.config.enabled:
            return
        body = None
        headers = resp.headers or {}
        if should_capture_body(headers, self._capture.config):
            try:
                body = await resp.body()
            except Exception:
                body = None
        self._capture.add_response(
            request_id=req_id,
            status=resp.status,
            ok=resp.ok,
            headers=headers,
            body=body,
        )

    def _record_capture_failure(self, req_id: str, error: Optional[str]) -> None:
        if not self._capture or not self._capture.config.enabled:
            return
        self._capture.add_failure(req_id, error)
    
    def _get_or_create_page_state(self, page: Page) -> PageState:
        """Get or create state for a page."""
        if page not in self._page_states:
            self._page_states[page] = PageState()
        return self._page_states[page]
    
    @property
    def page(self) -> Page:
        """Get current page."""
        if not self._page:
            raise RuntimeError("No page available. Call connect() first.")
        return self._page

    @property
    def context(self) -> BrowserContext:
        """Get current browser context."""
        if not self._context:
            raise RuntimeError("No browser context available. Call connect() first.")
        return self._context
    
    @property
    def page_state(self) -> PageState:
        """Get current page state."""
        return self._get_or_create_page_state(self.page)
    
    async def navigate(self, url: str, timeout_ms: Optional[int] = None) -> str:
        """Navigate to URL. Returns final URL."""
        timeout = timeout_ms or self.timeout_ms
        await self.page.goto(url, timeout=timeout)
        return self.page.url
    
    async def snapshot(
        self,
        options: Optional[RoleSnapshotOptions] = None
    ) -> RoleSnapshotResult:
        """
        Take an accessibility snapshot of the current page.
        Returns snapshot with refs assigned to interactive elements.
        """
        options = options or RoleSnapshotOptions()
        
        # Get aria snapshot from Playwright
        aria_snapshot = await self.page.locator(":root").aria_snapshot()
        
        # Build role snapshot with refs
        result = build_role_snapshot_from_aria(aria_snapshot, options)
        
        # Store refs in page state
        state = self.page_state
        state.role_refs = result.refs
        state.role_refs_frame_selector = None
        active_target = self._active_target_id()
        if active_target:
            self._cache_role_refs(active_target, result.refs, None)
        
        logger.debug(f"Snapshot: {result.stats['refs']} refs, {result.stats['interactive']} interactive")
        return result

    async def snapshot_ai(
        self,
        options: Optional[RoleSnapshotOptions] = None,
        max_chars: Optional[int] = None
    ) -> RoleSnapshotResult:
        """
        Take an AI snapshot (if Playwright supports it) and parse refs.
        """
        options = options or RoleSnapshotOptions()
        page = self.page
        snapshot_fn = getattr(page, "_snapshot_for_ai", None)
        if not snapshot_fn:
            raise RuntimeError("Playwright AI snapshot is not available (_snapshot_for_ai missing)")
        raw = await snapshot_fn()
        if isinstance(raw, dict):
            snapshot_text = raw.get("full") or raw.get("snapshot") or ""
        else:
            snapshot_text = str(raw)

        truncated = False
        if max_chars is not None and max_chars > 0 and len(snapshot_text) > max_chars:
            snapshot_text = snapshot_text[: max_chars] + "\n...TRUNCATED..."
            truncated = True

        result = build_role_snapshot_from_ai(snapshot_text, options)
        if truncated:
            result.stats["truncated"] = 1

        state = self.page_state
        state.role_refs = result.refs
        state.role_refs_frame_selector = None
        active_target = self._active_target_id()
        if active_target:
            self._cache_role_refs(active_target, result.refs, None)

        logger.debug(f"AI snapshot: {result.stats['refs']} refs, {result.stats['interactive']} interactive")
        return result
    
    def ref_locator(self, ref: str) -> Locator:
        """
        Get a Playwright Locator for a ref (e.g., "e1").
        Requires a prior call to snapshot().
        """
        state = self.page_state
        
        # Normalize ref format
        normalized = ref
        if ref.startswith('@'):
            normalized = ref[1:]
        elif ref.startswith('ref='):
            normalized = ref[4:]
        
        # Look up ref info
        ref_info = state.role_refs.get(normalized)
        if not ref_info:
            raise ValueError(
                f'Unknown ref "{normalized}". '
                f'Run snapshot() and use a ref from the result.'
            )
        
        # Build locator via getByRole
        page = self.page
        if state.role_refs_frame_selector:
            scope = page.frame_locator(state.role_refs_frame_selector)
        else:
            scope = page
        
        # Get by role with optional name
        if ref_info.name:
            locator = scope.get_by_role(ref_info.role, name=ref_info.name, exact=True)
        else:
            locator = scope.get_by_role(ref_info.role)
        
        # Apply nth if needed
        if ref_info.nth is not None and ref_info.nth > 0:
            locator = locator.nth(ref_info.nth)
        
        return locator
    
    async def get_page_info(self) -> Dict[str, Any]:
        """Get current page info."""
        page = self.page
        return {
            "url": page.url,
            "title": await page.title(),
            "viewport": page.viewport_size
        }
    
    async def get_console_messages(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent console messages."""
        state = self.page_state
        messages = state.console_messages[-limit:] if limit else state.console_messages
        return [
            {
                "type": m.type,
                "text": m.text,
                "timestamp": m.timestamp,
                "url": m.url,
                "line": m.line_number
            }
            for m in messages
        ]
    
    async def get_network_requests(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent network requests."""
        state = self.page_state
        requests = state.requests[-limit:] if limit else state.requests
        return [
            {
                "id": r.id,
                "method": r.method,
                "url": r.url,
                "status": r.status,
                "ok": r.ok,
                "type": r.resource_type
            }
            for r in requests
        ]

    def start_capture(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        if not self._capture_config.enabled:
            return {"enabled": False, "error": "Capture disabled in settings"}
        capture_id = session_id or datetime.utcnow().strftime("%Y%m%d%H%M%S")
        self._capture = BrowserTrafficCapture(capture_id, self._capture_config)
        return {"enabled": True, "session_id": capture_id}

    def stop_capture(self, persist: bool = True) -> Dict[str, Any]:
        if not self._capture:
            return {"enabled": False, "error": "No active capture"}
        summary = self._capture.summary()
        if persist:
            path = self._capture.save()
            summary["path"] = path
        self._last_capture = self._capture
        self._capture = None
        return summary

    def capture_status(self) -> Dict[str, Any]:
        if not self._capture:
            status = {"enabled": False}
            if self._last_capture:
                status["last_session_id"] = self._last_capture.session_id
                status["last_events"] = len(self._last_capture.events)
            return status
        summary = self._capture.summary()
        summary["enabled"] = True
        return summary

    def export_capture(self, min_confidence: int = 40) -> Dict[str, Any]:
        capture = self._capture or self._last_capture
        if not capture:
            return {"enabled": False, "error": "No capture available"}
        contracts = capture.synthesize_contracts(min_confidence=min_confidence)
        contracts_path = capture.save_contracts(contracts)
        return {
            "enabled": True,
            "session_id": capture.session_id,
            "contracts": contracts,
            "count": len(contracts),
            "contracts_path": contracts_path,
        }
    
    def __enter__(self):
        raise TypeError("Use 'async with' instead")
    
    def __exit__(self, *args):
        pass
    
    async def __aenter__(self):
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()


@asynccontextmanager
async def browser_session(
    cdp_url: Optional[str] = None,
    headless: bool = True,
    slow_mo: int = 0,
    timeout_ms: int = 30000
):
    """
    Context manager for browser session.
    
    Usage:
        async with browser_session() as session:
            await session.navigate("https://example.com")
            snapshot = await session.snapshot()
    """
    session = BrowserSession(
        headless=headless,
        slow_mo=slow_mo,
        timeout_ms=timeout_ms
    )
    try:
        await session.connect(cdp_url)
        yield session
    finally:
        await session.disconnect()
