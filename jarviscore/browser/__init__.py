"""
jarviscore.browser — Ref-based browser automation using Playwright.

Ported from an earlier internal agent codebase's browser_control module.
Port of OpenClaw's browser control architecture to Python.

Key Components:
- BrowserController: High-level interface for web automation
- BrowserSession: Low-level browser connection management
- BrowserInteractions: Ref-based element interactions
- Snapshot utilities: Accessibility snapshot generation with refs

Usage:
    from jarviscore.browser import BrowserController, browser_controller

    async with browser_controller(headless=True) as browser:
        await browser.navigate("https://example.com")
        result = await browser.snapshot(interactive_only=True)
        await browser.click("e1")
        await browser.type("e2", "hello@example.com", submit=True)

Install:
    pip install jarviscore[browser]  # adds playwright
    playwright install chromium      # install browser binary
"""
import logging

logger = logging.getLogger(__name__)

# All imports are lazy — if playwright isn't installed, we provide
# clear error messages when the user tries to use browser features.

try:
    from .controller import BrowserController, BrowserConfig, ActionResult, browser_controller
    from .protocol import BrowserAction, BrowserActionResult, normalize_action, validate_action, SUPPORTED_ACTION_KINDS
    from .profiles import BrowserProfile, BrowserProfileRegistry
    from .dispatcher import BrowserDispatcher
    from .trace import BrowserTraceRecorder
    from .capture import BrowserTrafficCapture, CaptureConfig
    from .cdp import (
        is_loopback_host,
        get_headers_with_auth,
        append_cdp_path,
        normalize_cdp_ws_url,
        fetch_json,
        fetch_ok,
        with_cdp_socket,
    )
    from .route_dispatcher import BrowserRouteDispatcher, RouteRequest, RouteResponse
    from .session import BrowserSession, browser_session, PageState
    from .interactions import BrowserInteractions, BrowserInteractionError
    from .snapshot import (
        RoleRef,
        RoleSnapshotOptions,
        RoleSnapshotResult,
        build_role_snapshot_from_aria,
        parse_role_ref,
        INTERACTIVE_ROLES,
        CONTENT_ROLES,
        STRUCTURAL_ROLES,
    )
    _BROWSER_AVAILABLE = True
except ImportError as e:
    _BROWSER_AVAILABLE = False
    _BROWSER_IMPORT_ERROR = str(e)
    logger.debug("Browser module not available: %s", e)

    # Provide stub symbols so imports don't crash
    BrowserController = None  # type: ignore[assignment,misc]
    BrowserConfig = None  # type: ignore[assignment,misc]
    ActionResult = None  # type: ignore[assignment,misc]
    browser_controller = None  # type: ignore[assignment,misc]

__all__ = [
    "BrowserController",
    "BrowserConfig",
    "ActionResult",
    "browser_controller",
    "BrowserSession",
    "browser_session",
    "PageState",
    "BrowserInteractions",
    "BrowserInteractionError",
    "BrowserDispatcher",
    "BrowserTraceRecorder",
    "BrowserTrafficCapture",
    "CaptureConfig",
    "BrowserRouteDispatcher",
    "RouteRequest",
    "RouteResponse",
    "_BROWSER_AVAILABLE",
]
