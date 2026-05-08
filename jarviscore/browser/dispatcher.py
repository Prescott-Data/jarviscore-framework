"""
Browser action dispatcher (in-process routing).
"""
from typing import Dict, Any, Optional, List
import json
import hashlib
import time

from .controller import BrowserController, ActionResult
from .protocol import BrowserAction, BrowserActionResult, normalize_action, validate_action
from .profiles import BrowserProfileRegistry, BrowserProfile
from .controller import BrowserConfig
from .trace import BrowserTraceRecorder
# Settings replaced with env vars — see os.environ usage below


class BrowserDispatcher:
    def __init__(self, profile_registry: BrowserProfileRegistry, trace_recorder: Optional[BrowserTraceRecorder] = None):
        self.profile_registry = profile_registry
        self._controllers: Dict[str, BrowserController] = {}
        self._trace = trace_recorder or BrowserTraceRecorder()

    async def _get_controller(self, profile_name: Optional[str]) -> BrowserController:
        profile = self.profile_registry.ensure_allowed(profile_name)
        if not self.profile_registry.is_action_allowed(profile, "connect"):
            raise ValueError(f"Profile '{profile.name}' does not allow browser access")
        key = profile.name
        if key not in self._controllers:
            self._controllers[key] = BrowserController(profile.config)
            await self._controllers[key].connect()
        elif not self._controllers[key].is_connected():
            await self._controllers[key].connect()
        return self._controllers[key]

    def _ensure_inline_profile(self, raw_profile: Dict[str, Any]) -> str:
        try:
            raw_json = json.dumps(raw_profile, sort_keys=True, default=str)
        except TypeError:
            raw_json = str(raw_profile)
        digest = hashlib.sha256(raw_json.encode("utf-8")).hexdigest()[:10]
        name = raw_profile.get("name")
        if not isinstance(name, str) or not name:
            name = f"inline:{digest}"
        if self.profile_registry.get(name):
            return name

        def get_bool(key: str, alt: str) -> Optional[bool]:
            value = raw_profile.get(key)
            if value is None:
                value = raw_profile.get(alt)
            if isinstance(value, bool):
                return value
            return None

        config = BrowserConfig(
            headless=bool(raw_profile.get("headless", True)),
            slow_mo=int(raw_profile.get("slow_mo", 0)),
            timeout_ms=int(raw_profile.get("timeout_ms", 30000)),
            cdp_url=raw_profile.get("cdp_url"),
            user_data_dir=raw_profile.get("user_data_dir"),
            launch_args=raw_profile.get("launch_args"),
            user_agent=raw_profile.get("user_agent"),
            locale=raw_profile.get("locale"),
            timezone_id=raw_profile.get("timezone_id"),
            viewport=raw_profile.get("viewport"),
            geolocation=raw_profile.get("geolocation"),
            permissions=raw_profile.get("permissions"),
            ignore_https_errors=get_bool("ignore_https_errors", "ignoreHTTPSErrors"),
            stealth_enabled=get_bool("stealth_enabled", "stealth"),
            profile_name=name,
        )
        self.profile_registry.register(BrowserProfile(name=name, config=config))
        return name

    async def dispatch(self, raw_action: Dict[str, Any]) -> BrowserActionResult:
        action = normalize_action(raw_action)
        validate_action(action)

        profile_name: Optional[str] = action.profile
        if isinstance(profile_name, dict):
            profile_name = self._ensure_inline_profile(profile_name)

        profile = self.profile_registry.ensure_allowed(profile_name)
        if not self.profile_registry.is_action_allowed(profile, action.kind):
            return BrowserActionResult(
                success=False,
                error=f"Action '{action.kind}' not allowed for profile '{profile.name}'",
                kind=action.kind,
            )

        controller = await self._get_controller(profile.name)
        payload = action.payload or {}
        if action.target_id:
            await controller.session.set_active_target(action.target_id)
        started = time.time()

        # Route actions
        if action.kind == "navigate":
            result = await controller.navigate(payload["url"], timeout_ms=payload.get("timeout_ms"))
        elif action.kind == "snapshot":
            result = await controller.snapshot(
                interactive_only=bool(payload.get("interactive_only", True)),
                compact=bool(payload.get("compact", True)),
                max_name_length=payload.get("max_name_length"),
            )
        elif action.kind == "snapshot_ai":
            result = await controller.snapshot_ai(
                interactive_only=bool(payload.get("interactive_only", True)),
                compact=bool(payload.get("compact", True)),
                max_chars=payload.get("max_chars"),
            )
        elif action.kind == "click":
            result = await controller.click(
                payload["ref"],
                double_click=bool(payload.get("double_click", False)),
                timeout_ms=payload.get("timeout_ms"),
            )
        elif action.kind == "type":
            result = await controller.type(
                payload["ref"],
                payload.get("text", ""),
                submit=bool(payload.get("submit", False)),
                slowly=bool(payload.get("slowly", False)),
                timeout_ms=payload.get("timeout_ms"),
            )
        elif action.kind == "hover":
            result = await controller.hover(payload["ref"], timeout_ms=payload.get("timeout_ms"))
        elif action.kind == "select":
            result = await controller.select(payload["ref"], payload.get("values") or [], timeout_ms=payload.get("timeout_ms"))
        elif action.kind == "check":
            result = await controller.check(payload["ref"], checked=bool(payload.get("checked", True)), timeout_ms=payload.get("timeout_ms"))
        elif action.kind == "drag":
            result = await controller.drag(payload["start_ref"], payload["end_ref"], timeout_ms=payload.get("timeout_ms"))
        elif action.kind == "scroll":
            result = await controller.scroll_to(payload["ref"], timeout_ms=payload.get("timeout_ms"))
        elif action.kind == "wait":
            result = await controller.wait(
                time_ms=payload.get("time_ms"),
                text=payload.get("text"),
                text_gone=payload.get("text_gone"),
                url=payload.get("url"),
                load_state=payload.get("load_state"),
                timeout_ms=payload.get("timeout_ms"),
            )
        elif action.kind == "evaluate":
            result = await controller.evaluate(payload.get("expression", ""), ref=payload.get("ref"))
        elif action.kind == "screenshot":
            result = await controller.screenshot(
                ref=payload.get("ref"),
                full_page=bool(payload.get("full_page", False)),
                format=payload.get("format", "png"),
            )
        elif action.kind == "get_text":
            result = await controller.get_text(payload["ref"], timeout_ms=payload.get("timeout_ms"))
        elif action.kind == "upload":
            result = await controller.upload_files(
                ref=payload.get("ref"),
                element=payload.get("element"),
                paths=payload.get("paths") or [],
            )
        elif action.kind == "download":
            result = await controller.download(
                ref=payload["ref"],
                path=payload.get("path"),
                timeout_ms=payload.get("timeout_ms"),
            )
        elif action.kind == "cookies_get":
            result = await controller.cookies_get(url=payload.get("url"))
        elif action.kind == "cookies_set":
            result = await controller.cookies_set(cookie=payload.get("cookie") or {})
        elif action.kind == "cookies_clear":
            result = await controller.cookies_clear()
        elif action.kind == "storage_get":
            result = await controller.storage_get(kind=payload.get("kind"), key=payload.get("key"))
        elif action.kind == "storage_set":
            result = await controller.storage_set(
                kind=payload.get("kind"),
                key=payload.get("key"),
                value=payload.get("value", ""),
            )
        elif action.kind == "storage_clear":
            result = await controller.storage_clear(kind=payload.get("kind"))
        elif action.kind == "offline":
            result = await controller.set_offline(offline=bool(payload.get("offline", False)))
        elif action.kind == "pdf":
            result = await controller.pdf(path=payload.get("path"))
        elif action.kind == "capture_start":
            result = await controller.capture_start(session_id=payload.get("session_id"))
        elif action.kind == "capture_stop":
            result = await controller.capture_stop(persist=bool(payload.get("persist", True)))
        elif action.kind == "capture_status":
            result = await controller.capture_status()
        elif action.kind == "capture_export":
            result = await controller.capture_export(min_confidence=int(payload.get("min_confidence", 40)))
        elif action.kind == "close":
            await controller.disconnect()
            result = ActionResult(success=True, data={"closed": True})
            self._controllers.pop(profile.name, None)
        else:
            return BrowserActionResult(success=False, error=f"Unhandled action kind: {action.kind}", kind=action.kind)

        duration_ms = int((time.time() - started) * 1000)
        data = result.data if isinstance(result.data, dict) else None
        if data and "bytes" in data:
            data = {**data, "bytes": "<redacted>"}
        active_target_id = controller.get_active_target_id()
        if active_target_id:
            data = data or {}
            data["target_id"] = active_target_id
            if isinstance(result.data, dict):
                result.data["target_id"] = active_target_id

        if result.error:
            data = data or {}
            error_type = self._classify_error(result.error)
            data["error_type"] = error_type
            if isinstance(result.data, dict):
                result.data["error_type"] = error_type
            elif result.data is None:
                result.data = {"error_type": error_type}

        if os.environ.get("BROWSER_TRACE_SCREENSHOTS", "false").lower() in ("1", "true", "yes") and action.kind not in ("screenshot", "snapshot", "snapshot_ai", "pdf"):
            try:
                shot = await controller.screenshot(
                    full_page=os.environ.get("BROWSER_TRACE_SCREENSHOT_FULL_PAGE", "false").lower() in ("1", "true", "yes"),
                    format="png",
                )
                if shot.success and isinstance(shot.data, dict):
                    image_bytes = shot.data.get("bytes")
                    if isinstance(image_bytes, (bytes, bytearray)):
                        path = self._trace.save_screenshot(bytes(image_bytes), format="png")
                        if path:
                            url = self._trace.build_screenshot_url(path)
                            data = data or {}
                            data["screenshot_path"] = path
                            data["screenshot_format"] = "png"
                            if url:
                                data["screenshot_url"] = url
                            if isinstance(result.data, dict):
                                result.data["screenshot_path"] = path
                                result.data["screenshot_format"] = "png"
                                if url:
                                    result.data["screenshot_url"] = url
            except Exception:
                pass

        self._trace.record_action(
            kind=action.kind,
            profile=profile.name,
            target_id=action.target_id,
            success=bool(result.success),
            duration_ms=duration_ms,
            error=result.error,
            data=data,
        )

        return BrowserActionResult(
            success=bool(result.success),
            data=result.data,
            error=result.error,
            kind=action.kind,
            ref=getattr(result, "ref", None),
        )

    @staticmethod
    def _classify_error(message: str) -> str:
        msg = (message or "").lower()
        if "not connected" in msg:
            return "NOT_CONNECTED"
        if "cdp" in msg and "reach" in msg:
            return "CDP_UNREACHABLE"
        if "timeout" in msg:
            return "TIMEOUT"
        if "tab not found" in msg or "target" in msg:
            return "TARGET_NOT_FOUND"
        if "navigation" in msg:
            return "NAVIGATION_FAILED"
        if "ref" in msg and "unknown" in msg:
            return "REF_NOT_FOUND"
        return "UNKNOWN"

    async def dispatch_batch(
        self,
        actions: List[Dict[str, Any]],
        snapshot_after: bool = True,
    ) -> BrowserActionResult:
        """Execute a planned sequence of browser actions atomically.

        Each action is dispatched in order through the full normalization,
        validation, and tracing pipeline. Execution stops on first failure.
        If ``snapshot_after`` is True, a snapshot is taken after the last
        successful action so the caller sees the resulting page state.

        This is the Cognitive Offloading principle: the LLM plans N actions
        in one turn; the dispatcher executes them deterministically without
        requiring N LLM round-trips.
        """
        step_results: List[Dict[str, Any]] = []
        for i, raw_action in enumerate(actions):
            try:
                result = await self.dispatch(raw_action)
                step_results.append({
                    "index": i,
                    "kind": result.kind,
                    "success": result.success,
                    "error": result.error,
                })
                if not result.success:
                    break
            except Exception as exc:
                step_results.append({
                    "index": i,
                    "kind": raw_action.get("kind"),
                    "success": False,
                    "error": str(exc),
                })
                break

        final_snapshot = None
        if snapshot_after:
            try:
                snap = await self.dispatch({"kind": "snapshot"})
                if snap.success:
                    final_snapshot = snap.data
            except Exception:
                pass

        all_ok = bool(step_results) and all(r["success"] for r in step_results)
        return BrowserActionResult(
            success=all_ok,
            data={
                "results": step_results,
                "actions_executed": len(step_results),
                "actions_total": len(actions),
                "snapshot": final_snapshot,
            },
            kind="batch",
        )

    async def get_controller(self, profile_name: Optional[str] = None) -> BrowserController:
        """Public access to the underlying controller for a profile.

        Used by agents that need Playwright-specific APIs (e.g. page.request.get
        for raw HTTP via the browser network context) that are not part of the
        generic action protocol.
        """
        return await self._get_controller(profile_name)

    async def close_all(self) -> None:
        for ctrl in self._controllers.values():
            try:
                await ctrl.disconnect()
            except Exception:
                pass
        self._controllers.clear()

