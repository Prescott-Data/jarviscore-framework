"""
OAuth flow handler for CLI environments without a backend.

Handles the interactive OAuth consent flow:
1. Opens auth URL in system browser (or prints it for headless)
2. Spins up a temporary local HTTP server to catch the callback
3. Polls Dromos Gateway until connection becomes ACTIVE
4. Returns control to AuthenticationManager

Pluggable: users can replace the default CLIFlowHandler with their own
(e.g., SlackFlowHandler that sends the URL via DM and waits for webhook).
"""

import asyncio
import logging
import threading
import webbrowser
from abc import ABC, abstractmethod
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any, Dict, Optional
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger(__name__)


class OAuthFlowHandler(ABC):
    """
    Abstract base for OAuth flow presentation.

    Subclass this to customize how auth URLs are presented to users
    and how the framework waits for completion.
    """

    @abstractmethod
    async def present_auth_url(self, auth_url: str, provider: str) -> None:
        """Present the OAuth URL to the user."""
        ...

    @abstractmethod
    async def wait_for_completion(
        self,
        connection_id: str,
        check_status_fn,
        timeout: float = 300,
        poll_interval: float = 2.0,
    ) -> str:
        """
        Wait for the OAuth flow to complete.

        Args:
            connection_id: The Nexus connection ID to monitor
            check_status_fn: Async callable that returns status string
            timeout: Max seconds to wait
            poll_interval: Seconds between status polls

        Returns:
            Final status string (ACTIVE, FAILED, etc.)
        """
        ...


class CLIFlowHandler(OAuthFlowHandler):
    """
    Default OAuth flow for CLI / terminal environments.

    - Tries to open auth URL in system browser
    - Falls back to printing the URL for manual copy
    - Polls connection status until ACTIVE or timeout
    """

    def __init__(self, open_browser: bool = True):
        self.open_browser = open_browser
        self._callback_server: Optional[LocalCallbackServer] = None

    async def present_auth_url(self, auth_url: str, provider: str) -> None:
        """Open browser and print URL as fallback."""
        # Start local server to receive the OAuth redirect
        self._callback_server = LocalCallbackServer(port=8080)
        self._callback_server.start()

        print(f"\n{'='*60}")
        print(f"  Authorization required for: {provider}")
        print(f"{'='*60}")

        opened = False
        if self.open_browser:
            try:
                opened = webbrowser.open(auth_url)
            except Exception:
                opened = False

        if opened:
            print(f"  Browser opened. Complete the sign-in flow there.")
        else:
            print(f"  Open this URL in your browser to authorize:")
            print(f"  {auth_url}")

        print(f"\n  Waiting for authorization...")
        print(f"{'='*60}\n")

    async def wait_for_completion(
        self,
        connection_id: str,
        check_status_fn,
        timeout: float = 300,
        poll_interval: float = 2.0,
        failed_grace_period: float = 120.0,
    ) -> str:
        """
        Poll connection status until ACTIVE or timeout.

        failed_grace_period: seconds to keep polling even when gateway
        returns FAILED, to work around gateways that map "token not yet
        available" (HTTP 403 from broker) as FAILED instead of PENDING.
        After the grace period, a persistent FAILED is treated as terminal.
        """
        try:
            elapsed = 0.0
            last_status = "PENDING"
            first_failed_at: Optional[float] = None

            while elapsed < timeout:
                try:
                    status = await check_status_fn(connection_id)
                except Exception as e:
                    logger.warning(f"Status check failed: {e}")
                    await asyncio.sleep(poll_interval)
                    elapsed += poll_interval
                    continue

                if status != last_status:
                    logger.info(f"Connection {connection_id}: {last_status} → {status}")
                    last_status = status

                if status == "ACTIVE":
                    print(f"  ✓ Authorization complete!")
                    return status

                if status in ("REVOKED", "EXPIRED"):
                    print(f"  ✗ Authorization failed: {status}")
                    return status

                if status == "FAILED":
                    if first_failed_at is None:
                        first_failed_at = elapsed
                        logger.debug(
                            f"Gateway returned FAILED at t={elapsed:.0f}s; "
                            f"will keep polling for {failed_grace_period:.0f}s grace period"
                        )
                    if elapsed - first_failed_at >= failed_grace_period:
                        print(f"  ✗ Authorization failed: FAILED")
                        return status
                    # Still within grace window — OAuth may not be complete yet
                else:
                    # Status recovered from FAILED; reset the grace timer
                    first_failed_at = None

                if status == "ATTENTION":
                    print(f"  ! Re-authorization may be needed")

                await asyncio.sleep(poll_interval)
                elapsed += poll_interval

            print(f"  ✗ Authorization timed out after {timeout}s")
            return "TIMEOUT"
        finally:
            if self._callback_server:
                self._callback_server.stop()
                self._callback_server = None


class _CallbackHandler(BaseHTTPRequestHandler):
    """HTTP request handler for OAuth callback."""

    auth_code: Optional[str] = None
    error: Optional[str] = None

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if "code" in params:
            _CallbackHandler.auth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h2>Authorization successful!</h2>"
                b"<p>You can close this tab and return to the terminal.</p>"
                b"</body></html>"
            )
        elif "connection_id" in params and params.get("status", [""])[0] == "success":
            # Dromos broker callback: ?connection_id=...&provider=...&status=success
            _CallbackHandler.auth_code = params["connection_id"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h2>Authorization successful!</h2>"
                b"<p>You can close this tab and return to the terminal.</p>"
                b"</body></html>"
            )
        elif "error" in params:
            _CallbackHandler.error = params.get("error_description", params["error"])[0]
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                f"<html><body><h2>Authorization failed</h2>"
                f"<p>{_CallbackHandler.error}</p></body></html>".encode()
            )
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        """Suppress default HTTP logging."""
        pass


class LocalCallbackServer:
    """
    Temporary HTTP server on localhost to catch OAuth redirects.

    Usage:
        server = LocalCallbackServer(port=8080)
        callback_url = server.callback_url  # http://localhost:8080/callback
        server.start()
        # ... user completes OAuth, provider redirects to callback_url ...
        code = server.wait_for_code(timeout=120)
        server.stop()
    """

    def __init__(self, port: int = 8080):
        self.port = port
        self.callback_url = f"http://localhost:{port}/callback"
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self):
        """Start the callback server in a background thread."""
        _CallbackHandler.auth_code = None
        _CallbackHandler.error = None
        self._server = HTTPServer(("localhost", self.port), _CallbackHandler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        logger.info(f"OAuth callback server listening on {self.callback_url}")

    async def wait_for_code(self, timeout: float = 120) -> Optional[str]:
        """Wait for the OAuth callback to deliver an auth code."""
        elapsed = 0.0
        while elapsed < timeout:
            if _CallbackHandler.auth_code:
                return _CallbackHandler.auth_code
            if _CallbackHandler.error:
                logger.error(f"OAuth callback error: {_CallbackHandler.error}")
                return None
            await asyncio.sleep(0.5)
            elapsed += 0.5
        return None

    def stop(self):
        """Shut down the callback server."""
        if self._server:
            self._server.shutdown()
            self._server = None
            self._thread = None
            logger.info("OAuth callback server stopped")
