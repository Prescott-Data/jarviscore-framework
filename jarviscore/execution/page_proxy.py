"""The live browser page, reachable from confined code only through its parent.

Code an agent writes runs in a child with no network and no browser of its
own. Inside it, ``page`` stands in for the agent's page: every attribute read
and call is sent to the parent, which performs it on the real page and returns
the value, or a handle when the value is itself part of the page (a locator, a
frame, the keyboard). The parent decides what the code may reach: the page and
its parts, never the browser, its cookies, its network or the host's files.
Every click or key press that could commit the person is judged before it runs.
"""

from __future__ import annotations

import asyncio
import base64
import inspect
import json
from typing import Any, Awaitable, Callable, Dict, List, Optional

# ── Child side ──────────────────────────────────────────────────────────────


class PlaywrightError(Exception):
    """A page operation failed in the browser."""


class PlaywrightTimeoutError(PlaywrightError):
    """A page operation did not finish within its timeout."""


class ConsequentialActionRefused(PlaywrightError):
    """The action could commit the person; it was not performed."""


_ERRORS = {
    "timeout": PlaywrightTimeoutError,
    "refused": ConsequentialActionRefused,
    "denied": PermissionError,
}


class _Ready:
    """An awaitable already resolved by the parent, as the real coroutine would be."""

    __slots__ = ("_value",)

    def __init__(self, value: Any):
        self._value = value

    def __await__(self):
        if False:  # pragma: no cover - makes this a generator
            yield
        return self._value


class PageClient:
    """Sends page operations to the parent and turns replies into values or stand-ins."""

    def __init__(self, call: Callable[[str, dict], Any]):
        self._call = call
        self._methods: Dict[str, frozenset] = {}

    def request(self, payload: dict) -> dict:
        reply = self._call("browser", payload)
        if reply.get("error"):
            raise _ERRORS.get(reply.get("kind"), PlaywrightError)(reply["error"])
        return reply

    def decode(self, value: Any) -> Any:
        if isinstance(value, dict):
            if "__handle__" in value:
                if "methods" in value:
                    self._methods[value["type"]] = frozenset(value["methods"])
                return RemoteObject(self, value["__handle__"], value["type"])
            if "__bytes__" in value and len(value) == 1:
                return base64.b64decode(value["__bytes__"])
            return {key: self.decode(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.decode(item) for item in value]
        return value

    def encode(self, value: Any) -> Any:
        if isinstance(value, RemoteObject):
            return {"__handle__": object.__getattribute__(value, "_handle")}
        if isinstance(value, dict):
            return {str(key): self.encode(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.encode(item) for item in value]
        if callable(value):
            raise TypeError(
                "Python functions cannot be passed to the page; pass JavaScript as a string "
                "(for example page.wait_for_function(\"() => ...\"))."
            )
        json.dumps(value)
        return value

    def methods(self, type_name: str) -> frozenset:
        return self._methods.get(type_name, frozenset())


class RemoteMethod:
    __slots__ = ("_client", "_handle", "_name")

    def __init__(self, client: PageClient, handle: int, name: str):
        self._client, self._handle, self._name = client, handle, name

    def __call__(self, *args, **kwargs):
        reply = self._client.request({
            "op": "call", "handle": self._handle, "name": self._name,
            "args": self._client.encode(list(args)), "kwargs": self._client.encode(kwargs),
        })
        value = self._client.decode(reply.get("value"))
        return _Ready(value) if reply.get("awaitable") else value


class RemoteObject:
    """A part of the page that lives in the parent: ``page``, a locator, a frame."""

    __slots__ = ("_client", "_handle", "_type")

    def __init__(self, client: PageClient, handle: int, type_name: str):
        object.__setattr__(self, "_client", client)
        object.__setattr__(self, "_handle", handle)
        object.__setattr__(self, "_type", type_name)

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        client = object.__getattribute__(self, "_client")
        handle = object.__getattribute__(self, "_handle")
        if name in client.methods(object.__getattribute__(self, "_type")):
            return RemoteMethod(client, handle, name)
        reply = client.request({"op": "get", "handle": handle, "name": name})
        if reply.get("method"):
            return RemoteMethod(client, handle, name)
        return client.decode(reply.get("value"))

    def __setattr__(self, name, value):
        raise AttributeError("Page objects are read through their methods, not assigned.")

    def __call__(self, *args, **kwargs):
        raise TypeError(f"'{object.__getattribute__(self, '_type')}' object is not callable")

    def __repr__(self) -> str:
        return f"<{object.__getattribute__(self, '_type')} #{object.__getattribute__(self, '_handle')}>"


def page_namespace(call: Callable[[str, dict], Any]) -> Dict[str, Any]:
    """What confined browser code is given: the page and the errors it can raise."""
    client = PageClient(call)
    page = client.decode(client.request({"op": "page"})["value"])

    def read_pages(urls, script, concurrency=0, next_page=None, until=None):
        """Each page's result of ``script``, reading several pages at once in this session.

        With ``next_page`` each address is a paged history, turned until ``until`` holds.
        """
        reply = client.request({
            "op": "read_pages", "urls": list(urls), "script": script, "concurrency": concurrency,
            "next_page": next_page or "", "until": until or "",
        })
        return _Ready(client.decode(reply.get("value")))

    def open_each(items, script, *rest, indexes=None, concurrency=0):
        """Each item of a list clicked in its own tab and read by ``script``.

        ``items`` is a locator for the items on the current page; ``open_each(url, selector,
        script)`` names a list page and its items' selector instead.
        """
        if isinstance(items, RemoteObject):
            request = {"items": client.encode(items), "script": script}
        elif rest:
            request = {"url": items, "selector": script, "script": rest[0]}
            if len(rest) > 1:
                indexes = rest[1]
            if len(rest) > 2:
                concurrency = rest[2]
        else:
            raise TypeError("open_each takes (items_locator, script) or (list_url, selector, script)")
        reply = client.request({
            "op": "open_each", **request,
            "indexes": list(indexes) if indexes is not None else None, "concurrency": concurrency,
        })
        return _Ready(client.decode(reply.get("value")))

    return {
        "page": page,
        "read_pages": read_pages,
        "open_each": open_each,
        "PlaywrightError": PlaywrightError,
        "PlaywrightTimeoutError": PlaywrightTimeoutError,
        "ConsequentialActionRefused": ConsequentialActionRefused,
    }


# ── Parent side ─────────────────────────────────────────────────────────────

#: Reachable by no type: the browser beyond the page, the network, host files, callbacks.
_DENIED = frozenset({
    "context", "route", "route_from_har", "route_web_socket", "unroute", "unroute_all",
    "expose_function", "expose_binding", "add_init_script", "set_extra_http_headers",
    "add_script_tag", "add_style_tag", "set_input_files", "set_content", "pdf", "video",
    "pause", "close", "on", "once", "remove_listener", "wait_for_event", "add_locator_handler",
    "remove_locator_handler", "bring_to_front", "set_default_navigation_timeout",
    "set_default_timeout", "clock", "workers", "service_workers",
})
_ELEMENT_ACTIONS = frozenset({
    "click", "dblclick", "tap", "check", "uncheck", "set_checked", "select_option",
    "dispatch_event", "drag_to", "drag_and_drop",
})
_TEXT_ACTIONS = frozenset({"type", "press_sequentially", "insert_text"})
_INPUT_ACTIONS = frozenset({"fill", "type", "press", "press_sequentially", "clear", "hover"})
# Reads of one element wait for it to appear; after settling, one that matches nothing is not there.
_ELEMENT_READS = frozenset({
    "inner_text", "text_content", "inner_html", "get_attribute", "input_value", "evaluate",
    "is_checked", "aria_snapshot",
})
_SCRIPTS = frozenset({"evaluate", "evaluate_all", "evaluate_handle", "wait_for_function"})
_NAVIGATION = frozenset({"goto", "reload", "go_back", "go_forward"})
_ONE_PAGE = (
    "This program already moved the page once, to {url}. A program works on the page it "
    "opens. Going on to other addresses is reading a collection: `await read_pages(urls, js)` "
    "reads addresses several at a time, and `await open_each(items, js)` opens items that "
    "open by clicking. The program's variables and state are kept."
)

_FINGERPRINT = """el => el ? ({
  tag: el.tagName, role: el.getAttribute('role'), type: el.getAttribute('type'),
  label: el.getAttribute('aria-label') || (el.labels && el.labels[0] ? el.labels[0].innerText : null),
  text: (el.innerText || el.value || '').trim().slice(0, 200),
  href: el.getAttribute('href'),
  form: el.form ? (el.form.getAttribute('aria-label') || el.form.action) : null
}) : null"""


def _commits_by_key(key: str) -> bool:
    keys = {part.strip().lower() for part in str(key).split("+")}
    return bool(keys & {"enter", "numpadenter", "space", " "}) or key == " "


class PageBroker:
    """Performs confined code's page operations on the real page, within what it may reach.

    ``judge`` receives a description of a possibly committing action and returns
    why it was refused, or None to let it run. ``pace`` spaces navigations to a site.
    """

    def __init__(
        self,
        page,
        judge: Callable[[Dict[str, Any]], Awaitable[Optional[str]]],
        pace: Optional[Callable[[str], Awaitable[None]]] = None,
        settle: Optional[Callable[[], Awaitable[None]]] = None,
        reader: Optional[Callable[[List[str], str, int], Awaitable[List[Dict[str, Any]]]]] = None,
        opener: Optional[Callable[..., Awaitable[List[Any]]]] = None,
    ):
        self.page = page
        self._judge = judge
        self._pace = pace
        self._settle = settle
        self._reader = reader
        self._opener = opener
        self._objects: Dict[int, Any] = {0: page}
        self._handles: Dict[int, int] = {id(page): 0}
        self._typed: set = set()
        self._verdicts: Dict[str, Optional[str]] = {}
        self._pointer = (0.0, 0.0)
        self.actions: List[Dict[str, Any]] = []
        self.state: Dict[str, Any] = {}
        #: Loop time after which the running program's page calls are no longer served.
        self.deadline: Optional[float] = None
        #: Where the running program moved the page, once it has.
        self.navigated: Optional[str] = None

    @staticmethod
    def _allowed_types() -> tuple:
        from playwright.async_api import (
            ElementHandle, Frame, FrameLocator, JSHandle, Keyboard, Locator, Mouse, Page, Request,
            Response,
        )

        return (
            Page, Frame, Locator, FrameLocator, Keyboard, Mouse, Response, Request, ElementHandle,
            JSHandle,
        )

    def _method_names(self, cls) -> List[str]:
        return sorted(
            name for name in dir(cls)
            if not name.startswith("_") and name not in _DENIED
            and not name.startswith("expect_") and callable(getattr(cls, name, None))
        )

    def _encode(self, value: Any) -> Any:
        if isinstance(value, self._allowed_types()):
            handle = self._handles.get(id(value))
            if handle is None:
                handle = len(self._objects)
                self._objects[handle] = value
                self._handles[id(value)] = handle
            name = type(value).__name__
            encoded: Dict[str, Any] = {"__handle__": handle, "type": name}
            if name not in self._typed:
                self._typed.add(name)
                encoded["methods"] = self._method_names(type(value))
            return encoded
        if isinstance(value, dict):
            return {str(key): self._encode(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._encode(item) for item in value]
        if value is None or isinstance(value, (str, int, float, bool, bytes)):
            return value
        raise PermissionError(f"{type(value).__name__} is outside the page and cannot be handed to code.")

    def _decode(self, value: Any) -> Any:
        if isinstance(value, dict):
            if "__handle__" in value and len(value) == 1:
                if value["__handle__"] not in self._objects:
                    raise PermissionError("Unknown page object.")
                return self._objects[value["__handle__"]]
            return {key: self._decode(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._decode(item) for item in value]
        return value

    def _target(self, payload: dict):
        handle = payload.get("handle")
        if handle not in self._objects:
            raise PermissionError("Unknown page object.")
        name = str(payload.get("name") or "")
        if not name or name.startswith("_") or name in _DENIED or name.startswith("expect_"):
            raise PermissionError(f"{name or 'That'} is outside what browser code may reach.")
        return self._objects[handle], name

    async def handle(self, payload: dict) -> dict:
        try:
            if isinstance(payload.get("state"), dict):
                self.state = payload["state"]
            op = payload.get("op")
            if op == "page":
                return {"value": self._encode(self.page)}
            if self.deadline is not None and asyncio.get_running_loop().time() >= self.deadline:
                return {
                    "error": "The program's time is up; its variables and state are kept for the next call.",
                    "kind": "timeout",
                }
            if op == "read_pages":
                return await self._read_pages(payload)
            if op == "open_each":
                return await self._open_each(payload)
            obj, name = self._target(payload)
            if op == "get":
                value = getattr(obj, name)
                if callable(value):
                    return {"method": True}
                return {"value": self._encode(value)}
            if op != "call":
                raise PermissionError("Unknown page operation.")
            args = self._decode(list(payload.get("args") or []))
            kwargs = self._decode(dict(payload.get("kwargs") or {}))
            if "path" in kwargs:
                raise PermissionError("Browser code cannot read or write files on the host.")
            # Network idle never comes on apps that poll; settle awaits the page's own data instead.
            if name in _NAVIGATION and kwargs.get("wait_until") == "networkidle":
                kwargs["wait_until"] = "domcontentloaded"
            if name == "wait_for_load_state" and "networkidle" in (args[:1] + [kwargs.get("state")]):
                if self._settle is not None:
                    await self._settle()
                return {"value": None, "awaitable": True}
            if name in _NAVIGATION and self.navigated is not None:
                return {"error": _ONE_PAGE.format(url=self.navigated), "kind": "denied"}
            refusal = await self._guard(obj, name, args, kwargs)
            if refusal:
                return {"error": refusal, "kind": "refused"}
            blocked = await self._not_actionable(obj, name)
            if blocked:
                return {"error": blocked, "kind": "playwright"}
            if name == "click":
                from playwright.async_api import Locator
                from jarviscore.kernel.defaults.browser import _TARGET_POINT

                if isinstance(obj, Locator):
                    point = await obj.evaluate(_TARGET_POINT, timeout=5000)
                    if point and not point["own"]:
                        value = await obj.evaluate("el => el.click()")
                        if self._settle is not None:
                            await self._settle()
                        return {"value": self._encode(value), "awaitable": True}
            out = getattr(obj, name)(*args, **kwargs)
            awaitable = inspect.isawaitable(out)
            if awaitable:
                out = await out
            if name in _NAVIGATION:
                self.navigated = self.page.url
            if self._settle is not None and name in (
                _NAVIGATION | _ELEMENT_ACTIONS | {"fill", "type", "press", "press_sequentially"}
            ):
                await self._settle()
            return {"value": self._encode(out), "awaitable": awaitable}
        except PermissionError as exc:
            return {"error": str(exc), "kind": "denied"}
        except Exception as exc:  # noqa: BLE001 - the page's own failure goes back to the code
            kind = "timeout" if type(exc).__name__ == "TimeoutError" else "playwright"
            return {"error": str(exc), "kind": kind}

    async def _read_pages(self, payload: dict) -> dict:
        """Read many pages at once in the same session: one judged script, each page paced and settled."""
        from urllib.parse import urlsplit

        if self._reader is None:
            raise PermissionError("read_pages is not available in this browser.")
        urls = [str(url) for url in payload.get("urls") or []]
        script = str(payload.get("script") or "")
        if not script:
            raise PermissionError("read_pages needs a JavaScript function to run on each page.")
        next_page, until = str(payload.get("next_page") or ""), str(payload.get("until") or "")
        for site in dict.fromkeys(urlsplit(url).netloc for url in urls):
            refusal = await self._decide({"action": "evaluate", "script": script, "url": f"https://{site}/"})
            if not refusal and until:
                refusal = await self._decide({"action": "evaluate", "script": until, "url": f"https://{site}/"})
            if not refusal and next_page:
                refusal = await self._decide({
                    "action": "click", "element": {"selector": next_page, "purpose": "turn to the next page"},
                    "url": f"https://{site}/",
                })
            if refusal:
                return {"error": refusal, "kind": "refused"}
        results = await self._reader(
            urls, script, int(payload.get("concurrency") or 0), next_page, until,
        )
        self.actions.append({"action": "read_pages", "pages": len(urls)})
        return {"value": self._encode(results), "awaitable": True}

    async def _open_each(self, payload: dict) -> dict:
        """Open every item a selector matches on a list page, several at once, and read what opens."""
        if self._opener is None:
            raise PermissionError("open_each is not available in this browser.")
        script = str(payload.get("script") or "")
        if payload.get("items") is not None:
            from playwright.async_api import Locator

            locator = self._decode(payload["items"])
            impl = getattr(locator, "_impl_obj", None)
            frame = getattr(impl, "_frame", None)
            if not isinstance(locator, Locator) or frame is None:
                raise PermissionError("open_each takes a locator for the list's items on this page.")
            if getattr(frame, "_parent_frame", None) is not None:
                raise PermissionError("open_each opens items of a list in the page itself, not inside a frame.")
            # Each tab reloads this page and finds the items again by the same selector, filters included.
            url, selector = self.page.url, str(getattr(impl, "_selector", "") or "")
            sample = await locator.evaluate_all("els => els.map(e => (e.innerText || '').trim())")
        else:
            url, selector = str(payload.get("url") or ""), str(payload.get("selector") or "")
            sample = await self._opener(url, selector, None, "", 0) if url and selector else []
        if not url or not selector or not script:
            raise PermissionError("open_each needs the list's items and a JavaScript function to run on what opens.")
        refusal = await self._decide({"action": "click", "element": {"selector": selector, "items": sample}, "url": url})
        refusal = refusal or await self._decide({"action": "evaluate", "script": script, "url": url})
        if refusal:
            return {"error": refusal, "kind": "refused"}
        indexes = payload.get("indexes")
        results = await self._opener(
            url, selector,
            [int(i) for i in indexes] if indexes is not None else list(range(len(sample))),
            script, int(payload.get("concurrency") or 0), count=len(sample),
        )
        self.actions.append({"action": "open_each", "url": url, "items": len(results)})
        return {"value": self._encode(results), "awaitable": True}

    async def _guard(self, obj, name: str, args: list, kwargs: dict) -> Optional[str]:
        from playwright.async_api import Keyboard, Mouse

        url = self.page.url
        if name in _NAVIGATION:
            destination = str(args[0] if args else kwargs.get("url") or url) if name == "goto" else url
            if self._pace is not None:
                await self._pace(destination)
            self.actions.append({"action": name, "url": destination})
            return None
        if name in _SCRIPTS:
            script = args[0] if args else kwargs.get("expression") or kwargs.get("expression_")
            return await self._decide({"action": name, "script": script, "url": url})
        if isinstance(obj, Mouse):
            if name in {"move", "click", "dblclick"} and len(args) >= 2:
                self._pointer = (float(args[0]), float(args[1]))
            if name not in {"click", "dblclick", "down"}:
                return None
            element = await self._fingerprint_at(*self._pointer)
            return await self._decide({"action": f"mouse.{name}", "element": element, "url": url})
        if isinstance(obj, Keyboard):
            text = str(args[0] if args else kwargs.get("key") or kwargs.get("text") or "")
            if name in {"press", "down"} and _commits_by_key(text) or name in _TEXT_ACTIONS and "\n" in text:
                element = await self._focused()
                return await self._decide({"action": f"keyboard.{name}", "key": text, "element": element, "url": url})
            return None
        selector_first = not hasattr(obj, "nth")  # Page, Frame and ElementHandle have no nth
        is_handle = hasattr(obj, "as_element")
        if name in _ELEMENT_ACTIONS:
            value = args[1:] if selector_first and not is_handle else args
        elif name == "press":
            key = (args[1] if selector_first and not is_handle and len(args) > 1 else args[0] if args else kwargs.get("key")) or ""
            if not _commits_by_key(str(key)):
                return None
            value = [key]
        elif name in _TEXT_ACTIONS:
            text = (args[1] if selector_first and not is_handle and len(args) > 1 else args[0] if args else kwargs.get("text")) or ""
            if "\n" not in str(text):
                return None
            value = [text]
        else:
            return None
        target = obj
        if selector_first and not is_handle and args:
            target = obj.locator(str(args[0])).first
        element = await self._fingerprint(target)
        return await self._decide({
            "action": name, "element": element,
            "value": [v for v in value if isinstance(v, (str, int, float, bool, list))] or None,
            "url": url,
        })

    async def _not_actionable(self, obj, name: str) -> Optional[str]:
        """Why an element action or read cannot happen now, said at once instead of after a long wait."""
        from playwright.async_api import Locator
        from jarviscore.kernel.defaults.browser import _COVERED_BY

        if not isinstance(obj, Locator) or name not in _ELEMENT_ACTIONS | _INPUT_ACTIONS | _ELEMENT_READS:
            return None
        try:
            count = await obj.count()
            if count == 0:
                return f"{name} was not performed: {obj} matches nothing on {self.page.url}."
            if count > 1 or name in _ELEMENT_READS:
                return None  # Playwright's strict-mode error names several matches; a read needs no more
            if await obj.is_disabled():
                return f"{name} was not performed: {obj} is disabled."
            if await obj.evaluate("el => getComputedStyle(el).display === 'contents'"):
                return None  # a boxless element is acted on through what it contains
            if not await obj.is_visible():
                return f"{name} was not performed: {obj} is not visible."
            await obj.scroll_into_view_if_needed(timeout=2000)
            cover = await obj.evaluate(_COVERED_BY)
            if cover:
                return f"{name} was not performed: {obj} is covered by {cover}; deal with that first."
        except Exception:  # noqa: BLE001 - the action itself reports what is wrong
            return None
        return None

    async def _fingerprint(self, target) -> Dict[str, Any]:
        described: Dict[str, Any] = {"locator": str(target)}
        try:
            found = await target.evaluate(_FINGERPRINT, timeout=5000) if hasattr(target, "nth") else await target.evaluate(_FINGERPRINT)
            described.update(found or {})
        except Exception as exc:  # noqa: BLE001 - the action itself will report what is wrong
            described["unresolved"] = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
        return described

    async def _fingerprint_at(self, x: float, y: float) -> Dict[str, Any]:
        try:
            return await self.page.evaluate(
                f"([x, y]) => ({_FINGERPRINT})(document.elementFromPoint(x, y))", [x, y]
            ) or {"point": [x, y]}
        except Exception:  # noqa: BLE001
            return {"point": [x, y]}

    async def _focused(self) -> Dict[str, Any]:
        try:
            return await self.page.evaluate(f"() => ({_FINGERPRINT})(document.activeElement)") or {}
        except Exception:  # noqa: BLE001
            return {}

    async def _decide(self, action: Dict[str, Any]) -> Optional[str]:
        key = json.dumps(action, sort_keys=True, default=str)
        if key not in self._verdicts:
            self._verdicts[key] = await self._judge(action)
        refusal = self._verdicts[key]
        self.actions.append({**action, **({"refused": refusal} if refusal else {})})
        return refusal
