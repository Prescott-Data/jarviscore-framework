"""
BrowserSubAgent — Headless browser automation specialist.

Doctrine:
  The browser agent drives a real Chromium browser (via Playwright) to interact
  with web pages that require JavaScript, authentication, or dynamic content.
  It is NOT a replacement for web_search — use it only when the task cannot be
  accomplished with HTTP + BeautifulSoup.

  Session lifecycle:
  - One Playwright browser is launched per run() call
  - Pages are reused within a run to preserve cookies/auth state
  - The browser is closed after run() exits (context manager enforced)

  Tool philosophy:
  - Every tool returns {status, data/error} — never raises exceptions to LLM
  - Screenshots are base64-encoded for inline context injection
  - Selectors use CSS by default; XPath and text matching as fallbacks

Design principles:
  - Graceful degradation: if Playwright not installed, returns clear install message
  - Lazy Playwright import: framework loads without playwright installed
  - Page stability: wait_for_load_state("networkidle") by default
  - Anti-bot: realistic viewport, user-agent, and timing
"""

import asyncio
import base64
import logging
import os
import time
from typing import Any, Dict, List, Optional

from jarviscore.kernel.subagent import BaseSubAgent

logger = logging.getLogger(__name__)

# Check Playwright availability at import time (lazy — won't crash)
try:
    from playwright.async_api import async_playwright, Browser, BrowserContext, Page
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logger.debug("Playwright not installed — BrowserSubAgent unavailable (pip install playwright)")


class BrowserSubAgent(BaseSubAgent):
    """
    Headless browser automation subagent.

    Requires: pip install playwright && playwright install chromium

    Tools:
    - navigate: Go to a URL and wait for page load
    - click: Click an element by CSS selector or text
    - type_text: Type text into an input field
    - get_text: Extract text from an element or the whole page
    - get_attribute: Get a specific attribute from an element
    - screenshot: Take a screenshot (returns base64 PNG)
    - wait_for: Wait for an element to appear or disappear
    - evaluate: Run JavaScript on the page
    - get_links: Extract all links from the current page
    - fill_form: Fill multiple form fields at once
    - select_option: Select an option from a <select> dropdown
    - hover: Hover over an element (triggers hover effects)
    - scroll: Scroll the page or a specific element
    - get_cookies: Get current page cookies
    - close_page: Close the current page and open a fresh one
    """

    SYSTEM_PROMPT = """\
You are a BROWSER AUTOMATION SPECIALIST in a multi-agent orchestration framework.
Your job: navigate and interact with web pages to extract data or complete tasks.

## CRITICAL RULES

1. **NAVIGATE FIRST** — Always call navigate() before any other interaction.
2. **WAIT FOR LOAD** — Pages may load slowly. Use wait_for() to confirm elements exist
   before clicking or typing. Do not assume elements are immediately available.
3. **SCREENSHOT TO VERIFY** — When unsure about page state, take a screenshot first.
4. **CSS SELECTORS** — Use specific CSS selectors. Prefer IDs (#id) over classes (.class).
   If CSS fails, try XPath or text-based matching.
5. **HANDLE ERRORS** — If a tool returns status=error, take a screenshot to understand
   the current page state before retrying.
6. **DATA EXTRACTION** — Use get_text() or evaluate() for structured data. Note findings
   explicitly in your DONE summary.
7. **NO LOOPS** — Do not retry the same action more than twice. If stuck, take a screenshot,
   reason about what's happening, then try a different approach.
8. **DONE WITH EVIDENCE** — Your DONE summary must include the extracted data or
   a clear statement of what action was completed with proof (screenshot hash or text excerpt).

## WORKFLOW

1. navigate(url) → wait for load
2. wait_for(selector) → confirm target element is present
3. interact (click / type_text / fill_form)
4. get_text / get_attribute / evaluate → extract data
5. screenshot() → visual verification if needed
6. DONE with findings
"""

    def __init__(
        self,
        agent_id: str,
        llm_client,
        headless: bool = True,
        viewport: Optional[Dict] = None,
        redis_store=None,
        blob_storage=None,
    ):
        self.headless = headless
        self.viewport = viewport or {"width": 1280, "height": 720}

        # Playwright objects — initialized in _pre_run_hook, closed in _post_run_hook
        self._playwright = None
        self._browser: Optional["Browser"] = None
        self._context: Optional["BrowserContext"] = None
        self._page: Optional["Page"] = None
        self._current_url: str = ""

        super().__init__(
            agent_id=agent_id,
            role="browser",
            llm_client=llm_client,
            redis_store=redis_store,
            blob_storage=blob_storage,
        )

    def get_system_prompt(self) -> str:
        return self.SYSTEM_PROMPT

    def setup_tools(self) -> None:
        if not PLAYWRIGHT_AVAILABLE:
            # Register a single stub tool that explains how to install Playwright
            self.register_tool(
                "install_required",
                self._tool_install_required,
                "Playwright not installed. Params: {}",
                phase="thinking",
            )
            return

        self.register_tool(
            "navigate",
            self._tool_navigate,
            'Go to a URL. Params: {"url": "<url>", "wait_for": "networkidle|domcontentloaded|load"}',
            phase="action",
        )
        self.register_tool(
            "click",
            self._tool_click,
            'Click an element. Params: {"selector": "<css>", "text": "<optional text match>"}',
            phase="action",
        )
        self.register_tool(
            "type_text",
            self._tool_type_text,
            'Type text into an input. Params: {"selector": "<css>", "text": "<text>", "clear_first": true}',
            phase="action",
        )
        self.register_tool(
            "get_text",
            self._tool_get_text,
            'Get text from an element or page. Params: {"selector": "<css or empty for full page>", "max_chars": 5000}',
            phase="thinking",
        )
        self.register_tool(
            "get_attribute",
            self._tool_get_attribute,
            'Get an attribute from an element. Params: {"selector": "<css>", "attribute": "<attr>"}',
            phase="thinking",
        )
        self.register_tool(
            "screenshot",
            self._tool_screenshot,
            "Take a screenshot of the current page. Params: {}",
            phase="thinking",
        )
        self.register_tool(
            "wait_for",
            self._tool_wait_for,
            'Wait for an element. Params: {"selector": "<css>", "timeout_ms": 5000, "state": "visible|hidden|attached|detached"}',
            phase="thinking",
        )
        self.register_tool(
            "evaluate",
            self._tool_evaluate,
            'Run JavaScript on the page. Params: {"script": "<js expression>"}',
            phase="action",
        )
        self.register_tool(
            "get_links",
            self._tool_get_links,
            'Get all links from the page. Params: {"selector": "<optional css to scope>", "max": 50}',
            phase="thinking",
        )
        self.register_tool(
            "fill_form",
            self._tool_fill_form,
            'Fill multiple form fields. Params: {"fields": [{"selector": "<css>", "value": "<text>"}]}',
            phase="action",
        )
        self.register_tool(
            "select_option",
            self._tool_select_option,
            'Select a dropdown option. Params: {"selector": "<css>", "value": "<option value or label>"}',
            phase="action",
        )
        self.register_tool(
            "scroll",
            self._tool_scroll,
            'Scroll the page. Params: {"direction": "down|up|top|bottom", "pixels": 500}',
            phase="action",
        )
        self.register_tool(
            "get_cookies",
            self._tool_get_cookies,
            "Get all cookies for the current page. Params: {}",
            phase="thinking",
        )
        self.register_tool(
            "close_page",
            self._tool_close_page,
            "Close current page and open a fresh one. Params: {}",
            phase="action",
        )

    # ──────────────────────────────────────────────────────────────────────
    # Lifecycle — open/close browser per run()
    # ──────────────────────────────────────────────────────────────────────

    async def _pre_run_hook(self, state) -> None:
        """Launch Playwright browser before the OODA loop starts."""
        if not PLAYWRIGHT_AVAILABLE:
            return
        try:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=self.headless,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            self._context = await self._browser.new_context(
                viewport=self.viewport,
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                java_script_enabled=True,
            )
            self._page = await self._context.new_page()
            logger.info("[browser] Playwright browser launched (headless=%s)", self.headless)
        except Exception as e:
            logger.error("[browser] Failed to launch browser: %s", e)
            self._browser = None
            self._context = None
            self._page = None

    async def _post_run_hook(self) -> None:
        """Close browser after run() finishes."""
        try:
            if self._page:
                await self._page.close()
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception as e:
            logger.debug("[browser] Cleanup error (non-fatal): %s", e)
        finally:
            self._page = None
            self._context = None
            self._browser = None
            self._playwright = None

    def _ensure_page(self) -> Optional[Dict]:
        """Return error dict if browser not ready, None if ready."""
        if not self._page:
            return {
                "status": "error",
                "error": (
                    "Browser not initialized. "
                    "This usually means Playwright failed to launch. "
                    "Try: pip install playwright && playwright install chromium"
                ),
            }
        return None

    # ──────────────────────────────────────────────────────────────────────
    # Stub tool (no Playwright)
    # ──────────────────────────────────────────────────────────────────────

    async def _tool_install_required(self, **kwargs) -> Dict[str, Any]:
        return {
            "status": "error",
            "error": (
                "Playwright is not installed. "
                "Install it with: pip install playwright && playwright install chromium\n"
                "This task cannot be completed without a browser. "
                "Consider using the researcher's web_search or read_url tools instead."
            ),
        }

    # ──────────────────────────────────────────────────────────────────────
    # Tools
    # ──────────────────────────────────────────────────────────────────────

    async def _tool_navigate(
        self,
        url: str,
        wait_for: str = "networkidle",
        timeout_ms: int = 30000,
        **kwargs,
    ) -> Dict[str, Any]:
        """Navigate to a URL."""
        err = self._ensure_page()
        if err:
            return err
        try:
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            response = await self._page.goto(
                url,
                wait_until=wait_for,
                timeout=timeout_ms,
            )
            self._current_url = self._page.url
            title = await self._page.title()
            return {
                "status": "success",
                "url": self._current_url,
                "title": title,
                "http_status": response.status if response else None,
            }
        except Exception as e:
            return {"status": "error", "error": str(e), "url": url}

    async def _tool_click(
        self,
        selector: str = "",
        text: str = "",
        timeout_ms: int = 10000,
        **kwargs,
    ) -> Dict[str, Any]:
        """Click an element by CSS selector or visible text."""
        err = self._ensure_page()
        if err:
            return err
        try:
            if text and not selector:
                # Text-based click
                await self._page.get_by_text(text, exact=False).first.click(timeout=timeout_ms)
            elif selector:
                await self._page.click(selector, timeout=timeout_ms)
            else:
                return {"status": "error", "error": "Either selector or text is required"}
            await asyncio.sleep(0.5)  # Brief pause for page response
            return {"status": "success", "url": self._page.url}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def _tool_type_text(
        self,
        selector: str,
        text: str,
        clear_first: bool = True,
        delay_ms: int = 50,
        **kwargs,
    ) -> Dict[str, Any]:
        """Type text into an input field."""
        err = self._ensure_page()
        if err:
            return err
        try:
            if clear_first:
                await self._page.fill(selector, "", timeout=10000)
            await self._page.type(selector, text, delay=delay_ms)
            return {"status": "success", "selector": selector, "chars_typed": len(text)}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def _tool_get_text(
        self,
        selector: str = "",
        max_chars: int = 5000,
        **kwargs,
    ) -> Dict[str, Any]:
        """Extract text from an element or the full page."""
        err = self._ensure_page()
        if err:
            return err
        try:
            if selector:
                element = self._page.locator(selector).first
                text = await element.inner_text(timeout=10000)
            else:
                # Full page text — strip scripts and styles via JS
                text = await self._page.evaluate("""() => {
                    const clone = document.body.cloneNode(true);
                    clone.querySelectorAll('script, style, nav, footer').forEach(e => e.remove());
                    return clone.innerText;
                }""")
            text = str(text).strip()
            truncated = len(text) > max_chars
            if truncated:
                text = text[:max_chars] + "\n... [truncated]"
            return {
                "status": "success",
                "text": text,
                "char_count": len(text),
                "truncated": truncated,
                "url": self._page.url,
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def _tool_get_attribute(
        self,
        selector: str,
        attribute: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """Get an attribute value from an element."""
        err = self._ensure_page()
        if err:
            return err
        try:
            value = await self._page.get_attribute(selector, attribute, timeout=10000)
            return {
                "status": "success",
                "selector": selector,
                "attribute": attribute,
                "value": value,
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def _tool_screenshot(
        self,
        full_page: bool = False,
        **kwargs,
    ) -> Dict[str, Any]:
        """Take a screenshot of the current page."""
        err = self._ensure_page()
        if err:
            return err
        try:
            png_bytes = await self._page.screenshot(full_page=full_page)
            b64 = base64.b64encode(png_bytes).decode("utf-8")
            size_kb = len(png_bytes) // 1024
            title = await self._page.title()
            return {
                "status": "success",
                "url": self._page.url,
                "title": title,
                "size_kb": size_kb,
                "screenshot_b64": b64[:2000] + "...[truncated for context]" if len(b64) > 2000 else b64,
                "note": "Screenshot captured. Analyze the visual to determine next action.",
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def _tool_wait_for(
        self,
        selector: str,
        timeout_ms: int = 10000,
        state: str = "visible",
        **kwargs,
    ) -> Dict[str, Any]:
        """Wait for an element to reach the specified state."""
        err = self._ensure_page()
        if err:
            return err
        try:
            await self._page.wait_for_selector(
                selector,
                state=state,
                timeout=timeout_ms,
            )
            return {"status": "success", "selector": selector, "state": state}
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "selector": selector,
                "hint": "Element not found. Check selector with screenshot().",
            }

    async def _tool_evaluate(
        self,
        script: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """Execute JavaScript on the page and return the result."""
        err = self._ensure_page()
        if err:
            return err
        try:
            result = await self._page.evaluate(script)
            return {"status": "success", "result": result}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def _tool_get_links(
        self,
        selector: str = "",
        max: int = 50,
        **kwargs,
    ) -> Dict[str, Any]:
        """Extract all links from the current page."""
        err = self._ensure_page()
        if err:
            return err
        try:
            scope = f"'{selector} a'" if selector else "'a'"
            links = await self._page.evaluate(f"""() => {{
                const anchors = Array.from(document.querySelectorAll({scope}));
                return anchors.slice(0, {max}).map(a => ({{
                    text: a.innerText.trim().slice(0, 100),
                    href: a.href,
                    title: a.title || ''
                }})).filter(l => l.href && l.href.startsWith('http'));
            }}""")
            return {"status": "success", "links": links, "count": len(links)}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def _tool_fill_form(
        self,
        fields: List[Dict[str, str]],
        **kwargs,
    ) -> Dict[str, Any]:
        """Fill multiple form fields at once."""
        err = self._ensure_page()
        if err:
            return err
        results = []
        for field in fields:
            selector = field.get("selector", "")
            value = field.get("value", "")
            if not selector:
                results.append({"selector": selector, "status": "error", "error": "No selector"})
                continue
            try:
                await self._page.fill(selector, value, timeout=10000)
                results.append({"selector": selector, "status": "success"})
            except Exception as e:
                results.append({"selector": selector, "status": "error", "error": str(e)})
        success_count = sum(1 for r in results if r["status"] == "success")
        return {
            "status": "success" if success_count == len(fields) else "partial",
            "filled": success_count,
            "total": len(fields),
            "results": results,
        }

    async def _tool_select_option(
        self,
        selector: str,
        value: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """Select an option from a <select> dropdown."""
        err = self._ensure_page()
        if err:
            return err
        try:
            # Try by value first, then by label
            selected = await self._page.select_option(selector, value=value, timeout=10000)
            if not selected:
                selected = await self._page.select_option(selector, label=value, timeout=10000)
            return {"status": "success", "selector": selector, "selected": selected}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def _tool_scroll(
        self,
        direction: str = "down",
        pixels: int = 500,
        selector: str = "",
        **kwargs,
    ) -> Dict[str, Any]:
        """Scroll the page or a specific element."""
        err = self._ensure_page()
        if err:
            return err
        try:
            if direction == "top":
                await self._page.evaluate("window.scrollTo(0, 0)")
            elif direction == "bottom":
                await self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            elif direction == "up":
                await self._page.evaluate(f"window.scrollBy(0, -{pixels})")
            else:  # down
                await self._page.evaluate(f"window.scrollBy(0, {pixels})")
            await asyncio.sleep(0.3)
            return {"status": "success", "direction": direction, "pixels": pixels}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def _tool_get_cookies(self, **kwargs) -> Dict[str, Any]:
        """Get all cookies for the current page."""
        err = self._ensure_page()
        if err:
            return err
        try:
            cookies = await self._context.cookies()
            # Sanitize — don't leak httpOnly/secure flags values
            safe_cookies = [
                {"name": c["name"], "domain": c["domain"], "path": c["path"]}
                for c in cookies
            ]
            return {"status": "success", "count": len(safe_cookies), "cookies": safe_cookies}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def _tool_close_page(self, **kwargs) -> Dict[str, Any]:
        """Close the current page and open a fresh one."""
        err = self._ensure_page()
        if err:
            return err
        try:
            await self._page.close()
            self._page = await self._context.new_page()
            self._current_url = ""
            return {"status": "success", "message": "Fresh page opened. Call navigate() next."}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    # ──────────────────────────────────────────────────────────────────────
    # Run override — ensure browser is always closed even on exception
    # ──────────────────────────────────────────────────────────────────────

    async def run(self, task, context=None, max_turns=20, model=None, **kwargs):
        """Run with browser lifecycle management."""
        await self._pre_run_hook(None)  # type: ignore[arg-type]
        try:
            return await super().run(task, context, max_turns, model, **kwargs)
        finally:
            await self._post_run_hook()
