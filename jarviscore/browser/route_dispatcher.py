"""
In-process HTTP-style route dispatcher for browser actions.
Provides OpenClaw-like route parity without a server dependency.
"""
from dataclasses import dataclass
from typing import Any, Dict, Callable, Optional, List
import re

from .dispatcher import BrowserDispatcher


@dataclass
class RouteRequest:
    method: str
    path: str
    query: Dict[str, Any]
    body: Dict[str, Any]
    params: Dict[str, str]


@dataclass
class RouteResponse:
    status: int
    body: Any


def _to_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return None


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        return None


def _to_str(value: Any) -> str:
    return "" if value is None else str(value)


class BrowserRouteDispatcher:
    def __init__(self, dispatcher: BrowserDispatcher):
        self.dispatcher = dispatcher
        self._routes: List[Dict[str, Any]] = []
        self._register_default_routes()

    def register(self, method: str, path: str, handler: Callable[[RouteRequest], Any]) -> None:
        regex, param_names = self._compile_route(path)
        self._routes.append(
            {"method": method.upper(), "path": path, "regex": regex, "params": param_names, "handler": handler}
        )

    def _compile_route(self, path: str) -> tuple[re.Pattern, List[str]]:
        param_names: List[str] = []
        parts = path.split("/")
        regex_parts = []
        for part in parts:
            if part.startswith(":"):
                param_names.append(part[1:])
                regex_parts.append("([^/]+)")
            else:
                regex_parts.append(re.escape(part))
        regex = re.compile("^" + "/".join(regex_parts) + "$")
        return regex, param_names

    async def dispatch(self, method: str, path: str, query: Optional[Dict[str, Any]] = None, body: Optional[Dict[str, Any]] = None) -> RouteResponse:
        method = method.upper()
        query = query or {}
        body = body or {}
        path = path if path.startswith("/") else f"/{path}"
        for route in self._routes:
            if route["method"] != method:
                continue
            match = route["regex"].match(path)
            if not match:
                continue
            params = {}
            for idx, name in enumerate(route["params"]):
                params[name] = match.group(idx + 1)
            req = RouteRequest(method=method, path=path, query=query, body=body, params=params)
            try:
                result = await route["handler"](req)
                return RouteResponse(status=200, body=result)
            except Exception as e:
                return RouteResponse(status=500, body={"error": str(e)})
        return RouteResponse(status=404, body={"error": "Not Found"})

    def _register_default_routes(self) -> None:
        self.register("POST", "/navigate", self._handle_navigate)
        self.register("GET", "/snapshot", self._handle_snapshot)
        self.register("POST", "/act", self._handle_act)
        self.register("GET", "/cookies", self._handle_cookies_get)
        self.register("POST", "/cookies/set", self._handle_cookies_set)
        self.register("POST", "/cookies/clear", self._handle_cookies_clear)
        self.register("GET", "/storage/:kind", self._handle_storage_get)
        self.register("POST", "/storage/:kind/set", self._handle_storage_set)
        self.register("POST", "/storage/:kind/clear", self._handle_storage_clear)
        self.register("POST", "/set/offline", self._handle_set_offline)
        self.register("POST", "/screenshot", self._handle_screenshot)
        self.register("POST", "/pdf", self._handle_pdf)

    async def _handle_navigate(self, req: RouteRequest) -> Any:
        url = _to_str(req.body.get("url"))
        if not url:
            return {"error": "url is required"}
        action = {
            "kind": "navigate",
            "profile": req.body.get("profile"),
            "target_id": req.body.get("targetId") or req.body.get("target_id"),
            "payload": {"url": url, "timeout_ms": req.body.get("timeoutMs")},
        }
        result = await self.dispatcher.dispatch(action)
        return {"ok": result.success, "result": result.data, "error": result.error}

    async def _handle_snapshot(self, req: RouteRequest) -> Any:
        fmt = _to_str(req.query.get("format")).lower()
        interactive = _to_bool(req.query.get("interactive"))
        compact = _to_bool(req.query.get("compact"))
        max_chars = _to_int(req.query.get("maxChars"))
        kind = "snapshot_ai" if fmt == "ai" else "snapshot"
        action = {
            "kind": kind,
            "profile": req.query.get("profile"),
            "target_id": req.query.get("targetId"),
            "payload": {
                "interactive_only": interactive if interactive is not None else True,
                "compact": compact if compact is not None else True,
                "max_chars": max_chars,
            },
        }
        result = await self.dispatcher.dispatch(action)
        return {"ok": result.success, "result": result.data, "error": result.error}

    async def _handle_act(self, req: RouteRequest) -> Any:
        kind = _to_str(req.body.get("kind"))
        if not kind:
            return {"error": "kind is required"}
        payload = dict(req.body)
        payload.pop("kind", None)
        action = {
            "kind": kind,
            "profile": req.body.get("profile"),
            "target_id": req.body.get("targetId") or req.body.get("target_id"),
            "payload": payload,
        }
        result = await self.dispatcher.dispatch(action)
        return {"ok": result.success, "result": result.data, "error": result.error}

    async def _handle_cookies_get(self, req: RouteRequest) -> Any:
        action = {
            "kind": "cookies_get",
            "profile": req.query.get("profile"),
            "target_id": req.query.get("targetId"),
            "payload": {"url": req.query.get("url")},
        }
        result = await self.dispatcher.dispatch(action)
        return {"ok": result.success, "result": result.data, "error": result.error}

    async def _handle_cookies_set(self, req: RouteRequest) -> Any:
        action = {
            "kind": "cookies_set",
            "profile": req.body.get("profile"),
            "target_id": req.body.get("targetId") or req.body.get("target_id"),
            "payload": {"cookie": req.body.get("cookie")},
        }
        result = await self.dispatcher.dispatch(action)
        return {"ok": result.success, "result": result.data, "error": result.error}

    async def _handle_cookies_clear(self, req: RouteRequest) -> Any:
        action = {
            "kind": "cookies_clear",
            "profile": req.body.get("profile"),
            "target_id": req.body.get("targetId") or req.body.get("target_id"),
            "payload": {},
        }
        result = await self.dispatcher.dispatch(action)
        return {"ok": result.success, "result": result.data, "error": result.error}

    async def _handle_storage_get(self, req: RouteRequest) -> Any:
        kind = _to_str(req.params.get("kind"))
        action = {
            "kind": "storage_get",
            "profile": req.query.get("profile"),
            "target_id": req.query.get("targetId"),
            "payload": {"kind": kind, "key": req.query.get("key")},
        }
        result = await self.dispatcher.dispatch(action)
        return {"ok": result.success, "result": result.data, "error": result.error}

    async def _handle_storage_set(self, req: RouteRequest) -> Any:
        kind = _to_str(req.params.get("kind"))
        action = {
            "kind": "storage_set",
            "profile": req.body.get("profile"),
            "target_id": req.body.get("targetId") or req.body.get("target_id"),
            "payload": {"kind": kind, "key": req.body.get("key"), "value": req.body.get("value", "")},
        }
        result = await self.dispatcher.dispatch(action)
        return {"ok": result.success, "result": result.data, "error": result.error}

    async def _handle_storage_clear(self, req: RouteRequest) -> Any:
        kind = _to_str(req.params.get("kind"))
        action = {
            "kind": "storage_clear",
            "profile": req.body.get("profile"),
            "target_id": req.body.get("targetId") or req.body.get("target_id"),
            "payload": {"kind": kind},
        }
        result = await self.dispatcher.dispatch(action)
        return {"ok": result.success, "result": result.data, "error": result.error}

    async def _handle_set_offline(self, req: RouteRequest) -> Any:
        offline = _to_bool(req.body.get("offline"))
        action = {
            "kind": "offline",
            "profile": req.body.get("profile"),
            "target_id": req.body.get("targetId") or req.body.get("target_id"),
            "payload": {"offline": bool(offline)},
        }
        result = await self.dispatcher.dispatch(action)
        return {"ok": result.success, "result": result.data, "error": result.error}

    async def _handle_screenshot(self, req: RouteRequest) -> Any:
        action = {
            "kind": "screenshot",
            "profile": req.body.get("profile"),
            "target_id": req.body.get("targetId") or req.body.get("target_id"),
            "payload": {
                "ref": req.body.get("ref"),
                "full_page": req.body.get("fullPage"),
                "format": req.body.get("format", "png"),
            },
        }
        result = await self.dispatcher.dispatch(action)
        return {"ok": result.success, "result": result.data, "error": result.error}

    async def _handle_pdf(self, req: RouteRequest) -> Any:
        action = {
            "kind": "pdf",
            "profile": req.body.get("profile"),
            "target_id": req.body.get("targetId") or req.body.get("target_id"),
            "payload": {"path": req.body.get("path")},
        }
        result = await self.dispatcher.dispatch(action)
        return {"ok": result.success, "result": result.data, "error": result.error}
