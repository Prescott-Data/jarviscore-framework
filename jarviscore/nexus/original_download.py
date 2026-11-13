"""Internal, credential-free redirect transport for selected original downloads."""
from __future__ import annotations

import contextvars
import logging
import re
from urllib.parse import urlsplit

import httpx

MAX_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_BYTES = 16 * 1024 * 1024
MAX_REDIRECTS = 3
_REDIRECTS = {301, 302, 303, 307, 308}
_private_transport = contextvars.ContextVar("nexus_original_download_transport", default=False)


class _PrivateTransportLogs(logging.Filter):
    def filter(self, record):
        # httpx logs full URLs at INFO; httpcore DEBUG includes paths and headers.
        # Context-local filtering keeps unrelated, concurrent requests observable.
        return not _private_transport.get()


def private_transport_logs():
    names = {"httpx", "httpcore.connection", "httpcore.connection_pool", "httpcore.http11",
             "httpcore.http2", "httpcore.proxy", "httpcore.socks"}
    names.update(name for name in logging.Logger.manager.loggerDict if name.startswith("httpcore."))
    for name in names:
        logger = logging.getLogger(name)
        if not any(isinstance(item, _PrivateTransportLogs) for item in logger.filters):
            logger.addFilter(_PrivateTransportLogs())
    return _private_transport.set(True)


def restore_transport_logs(token):
    _private_transport.reset(token)


def exact_hosts(configuration):
    """Freeze operator configuration; never interpret wildcards, URLs or suffixes."""
    if not isinstance(configuration, dict):
        raise TypeError("Original download hosts must be an operator-configured mapping")
    result = {}
    for provider, hosts in configuration.items():
        if not isinstance(provider, str) or not isinstance(hosts, (list, tuple)):
            raise TypeError("Original download hosts must be exact host lists")
        checked = []
        for host in hosts:
            if not isinstance(host, str) or not re.fullmatch(
                r"(?=.{1,253}\Z)(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+"
                r"[a-zA-Z](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", host
            ):
                raise ValueError("Original download hosts must be exact DNS names")
            checked.append(host.lower())
        result[provider.lower()] = frozenset(checked)
    return result


def https_url(url):
    """Reject ambiguity before httpx normalizes an untrusted URL."""
    if not isinstance(url, str) or any(ord(char) <= 32 or ord(char) >= 127 for char in url) or "\\" in url:
        raise ValueError("Original downloads require an unambiguous HTTPS URL")
    try:
        parts = urlsplit(url)
        if (parts.scheme != "https" or not parts.hostname or parts.username is not None
                or parts.password is not None or parts.port not in (None, 443) or parts.fragment
                or "#" in url or parts.hostname.endswith(".")):
            raise ValueError
    except ValueError:
        raise ValueError("Original downloads require an unambiguous HTTPS URL") from None
    return parts.hostname.lower()


def validate_intent(method, url, headers, kwargs, max_bytes, timeout):
    https_url(url)
    if method.upper() not in ("GET", "POST") or set(kwargs) - {"params"}:
        raise ValueError("Original downloads accept GET or reviewed native read POST and selector params only")
    if type(max_bytes) is not int or not 0 < max_bytes <= MAX_BYTES:
        raise ValueError("Original download byte bound must be between 1 and 67108864")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 300:
        raise ValueError("Original download timeout must be between 0 and 300 seconds")
    try:
        effective = httpx.Headers(headers or {})
        if any(key in effective for key in ("authorization", "proxy-authorization", "cookie", "host")):
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError("Original download headers cannot supply transport credentials or routing") from None


def validate_read_post(call):
    # Dropbox documents this exact POST as a content download, not a mutation.
    # A caller's read label or verified model POST contract cannot grant it.
    from jarviscore.control.policy import TRUSTED_ORIGINS

    parts = urlsplit(call.url)
    if (call.provider != "dropbox" or parts.hostname != "content.dropboxapi.com"
            or parts.path != "/2/files/download" or call.code_origin not in TRUSTED_ORIGINS
            or not call.atom or call.declared_effect != "read" or not call.verified):
        raise ValueError("Original POST requires a verified native direct content-read operation")


def failure(status=0):
    return {"ok": False, "status_code": status, "body": "", "content": b"",
            "json": None, "headers": {}, "error": "Original download failed"}


def safe_headers(headers):
    result = {}
    content_type = headers.get("content-type", "").split(";", 1)[0].strip()
    if re.fullmatch(r"[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+", content_type):
        result["content-type"] = content_type
    for name in ("content-length", "retry-after"):
        value = headers.get(name, "")
        if re.fullmatch(r"[0-9]{1,20}", value):
            result[name] = value
    return result


async def transfer(client, initial_request, *, max_bytes, redirect_allowed, refresh):
    """Only a Location supplied by the authenticated selected source can enter here."""
    request = initial_request
    hops = 0
    refreshed = False
    while True:
        response = await client.send(request, stream=True, auth=None, follow_redirects=False)
        try:
            status = response.status_code
            if status == 401 and hops == 0 and not refreshed:
                refreshed = True
                await response.aclose()
                request = await refresh()
                continue
            if status in _REDIRECTS:
                locations = response.headers.get_list("location")
                if (initial_request.method != "GET" or hops >= MAX_REDIRECTS
                        or len(locations) != 1 or not redirect_allowed(locations[0])):
                    return failure(status)
                # No original query, headers, client cookies, default auth or selectors.
                request = httpx.Request("GET", locations[0], headers={
                    "Accept": "application/octet-stream", "Accept-Encoding": "identity"},
                    extensions=initial_request.extensions.copy())
                hops += 1
                continue
            if not 200 <= status < 300:
                return failure(status)
            if response.headers.get("content-encoding", "identity").lower() != "identity":
                return failure(status)
            length = response.headers.get("content-length")
            if length is not None and (not re.fullmatch(r"[0-9]{1,20}", length) or int(length) > max_bytes):
                return failure(status)
            content = bytearray()
            async for chunk in response.aiter_raw(chunk_size=min(65536, max_bytes + 1)):
                if len(content) + len(chunk) > max_bytes:
                    return failure(status)
                content.extend(chunk)
            if length is not None and int(length) != len(content):
                return failure(status)
            return {"ok": True, "status_code": status, "body": "", "content": bytes(content),
                    "json": None, "headers": safe_headers(response.headers)}
        finally:
            await response.aclose()
