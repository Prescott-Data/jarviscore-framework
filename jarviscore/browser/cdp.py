"""
Minimal CDP helpers for direct Chrome DevTools Protocol access.
"""
import asyncio
import base64
import json
from typing import Any, Dict, Optional, Callable, Awaitable
from urllib.parse import urlparse, urlunparse, ParseResult

import aiohttp
import websockets


def is_loopback_host(host: str) -> bool:
    h = host.strip().lower()
    return h in {"localhost", "127.0.0.1", "0.0.0.0", "[::1]", "::1", "[::]", "::"}


def get_headers_with_auth(url: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    merged = dict(headers or {})
    parsed = urlparse(url)
    has_auth = any(k.lower() == "authorization" for k in merged.keys())
    if not has_auth and (parsed.username or parsed.password):
        auth_raw = f"{parsed.username or ''}:{parsed.password or ''}"
        auth = base64.b64encode(auth_raw.encode("utf-8")).decode("utf-8")
        merged["Authorization"] = f"Basic {auth}"
    return merged


def append_cdp_path(cdp_url: str, path: str) -> str:
    parsed = urlparse(cdp_url)
    base_path = parsed.path.rstrip("/")
    suffix = path if path.startswith("/") else f"/{path}"
    return urlunparse(parsed._replace(path=f"{base_path}{suffix}"))


def normalize_cdp_ws_url(ws_url: str, cdp_url: str) -> str:
    ws = urlparse(ws_url)
    cdp = urlparse(cdp_url)
    ws_list = list(ws)
    if is_loopback_host(ws.hostname or "") and not is_loopback_host(cdp.hostname or ""):
        ws_list[1] = ws.netloc.replace(ws.hostname or "", cdp.hostname or "")
        if cdp.port:
            ws_list[1] = f"{cdp.hostname}:{cdp.port}"
        ws_list[0] = "wss" if cdp.scheme == "https" else "ws"
    if cdp.scheme == "https" and ws.scheme == "ws":
        ws_list[0] = "wss"
    return urlunparse(ParseResult(*ws_list))


async def fetch_json(url: str, timeout_ms: int = 1500, headers: Optional[Dict[str, str]] = None) -> Any:
    hdrs = get_headers_with_auth(url, headers)
    timeout = aiohttp.ClientTimeout(total=timeout_ms / 1000.0)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, headers=hdrs) as resp:
            resp.raise_for_status()
            return await resp.json()


async def fetch_ok(url: str, timeout_ms: int = 1500, headers: Optional[Dict[str, str]] = None) -> None:
    hdrs = get_headers_with_auth(url, headers)
    timeout = aiohttp.ClientTimeout(total=timeout_ms / 1000.0)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, headers=hdrs) as resp:
            resp.raise_for_status()


async def with_cdp_socket(
    ws_url: str,
    fn: Callable[[Callable[[str, Optional[Dict[str, Any]]], Awaitable[Any]]], Awaitable[Any]],
    headers: Optional[Dict[str, str]] = None,
) -> Any:
    hdrs = get_headers_with_auth(ws_url, headers)
    async with websockets.connect(ws_url, extra_headers=hdrs) as ws:
        next_id = 1
        pending: Dict[int, asyncio.Future] = {}

        async def send(method: str, params: Optional[Dict[str, Any]] = None) -> Any:
            nonlocal next_id
            msg_id = next_id
            next_id += 1
            payload = {"id": msg_id, "method": method, "params": params or {}}
            fut: asyncio.Future = asyncio.get_event_loop().create_future()
            pending[msg_id] = fut
            await ws.send(json.dumps(payload))
            return await fut

        async def recv_loop() -> None:
            async for raw in ws:
                try:
                    parsed = json.loads(raw)
                except Exception:
                    continue
                msg_id = parsed.get("id")
                if not isinstance(msg_id, int):
                    continue
                fut = pending.pop(msg_id, None)
                if not fut:
                    continue
                if parsed.get("error"):
                    fut.set_exception(RuntimeError(parsed["error"].get("message", "CDP error")))
                else:
                    fut.set_result(parsed.get("result"))

        recv_task = asyncio.create_task(recv_loop())
        try:
            return await fn(send)
        finally:
            recv_task.cancel()
