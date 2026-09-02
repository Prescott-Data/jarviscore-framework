import requests
from typing import Any, Dict, List, Optional



def pendo_get_event(auth_info: dict, event_id: str, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Fetch track event type by id/name via trackTypes aggregation filter. Official: https://engageapi.pendo.io/"""
    try:
        if not event_id:
            return _pn_dataset([], 400, "event_id is required")
        pipeline = [{"source": _pn_source(auth_info, "trackTypes")}, {"limit": 100000}]
        records, status, msg = _pn_aggregate(auth_info, pipeline, request_id="get-track-type", timeout=timeout, verify_ssl=verify_ssl)
        if status >= 400:
            return _pn_dataset([], status, msg)
        matches = [r for r in records if str(r.get("id", "")) == str(event_id) or str(r.get("trackTypeId", "")) == str(event_id) or str(r.get("name", "")).lower() == str(event_id).lower()]
        if not matches:
            matches = [r for r in records if _pn_match(r, event_id)]
        return _pn_dataset(matches[:1], 200 if matches else 404, "ok" if matches else "track type not found")

    except Exception as e:
        return _pn_dataset([], 500, str(e))


# Pendo Engage API — Official docs: https://engageapi.pendo.io/


def _pn_root(base_url, auth_info):
    auth_info = auth_info or {}
    root = (base_url or auth_info.get("pendo_url") or auth_info.get("base_url") or "https://app.pendo.io/api/v1").strip().rstrip("/")
    if "/api/v1" not in root:
        if root.endswith("/api"):
            root = root + "/v1"
        elif _host_is(root, "pendo.io"):
            root = root + "/api/v1"
    if not root:
        return None, "base_url is required (https://app.pendo.io/api/v1)"
    return root, None


def _pn_host(base_url, auth_info):
    auth_info = auth_info or {}
    root = (base_url or auth_info.get("pendo_url") or auth_info.get("base_url") or "https://app.pendo.io").strip().rstrip("/")
    if "/api/v1" in root:
        root = root.split("/api/v1")[0]
    return root.rstrip("/") or "https://app.pendo.io"


def _pn_key(auth_info, track=False):
    auth_info = auth_info or {}
    if track:
        return (
            auth_info.get("track_event_secret")
            or auth_info.get("track_shared_secret")
            or auth_info.get("track_secret")
        )
    return (
        auth_info.get("integration_key")
        or auth_info.get("api_key")
    )


def _pn_auth(auth_info, track=False, json_body=True):
    key = _pn_key(auth_info, track=track)
    if not key:
        if track:
            return None, "auth_info.track_event_secret is required for track ingest"
        return None, "auth_info.integration_key is required"
    headers = {"x-pendo-integration-key": str(key).strip()}
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers, None


def _pn_cap(limit):
    return min(max(int(limit or 25), 1), 100000)


def _pn_err(resp):
    try:
        data = resp.json()
        if isinstance(data, dict):
            msg = data.get("message") or data.get("error")
            if msg:
                return str(msg)[:1000]
    except Exception:
        pass
    return (resp.text or f"HTTP {resp.status_code}")[:1000]


def _pn_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _pn_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get("id") or obj.get("event") or obj.get("reference") or fallback_id
    ids = [pid] if pid not in (None, "") else []
    rec = obj if obj else ({"id": pid} if ids else {})
    return {"records": [rec] if rec else [], "data_count": 1 if rec else 0, "status": status, "message": msg, "provision_ids": ids}


def _pn_results(data):
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("results", "data", "rows", "reports"):
            items = data.get(key)
            if isinstance(items, list):
                return [x for x in items if isinstance(x, dict)]
        if data.get("id"):
            return [data]
    return []


def _pn_source(auth_info, source_name):
    auth_info = auth_info or {}
    app_id = auth_info.get("app_id") or auth_info.get("application_id")
    if app_id:
        return {source_name: {"appId": app_id}}
    if str(auth_info.get("expand_apps", "")).lower() in ("1", "true", "yes", "*"):
        return {source_name: {"appId": 'expandAppIds("*")'}}
    return {source_name: None}


def _pn_request(method, url, auth_info, params=None, json_body=None, timeout=30, verify_ssl=True, track=False):
    headers, err = _pn_auth(auth_info, track=track, json_body=(json_body is not None or method in ("post", "put")))
    if err:
        return None, None, 401, err
    kwargs = {"headers": headers, "timeout": timeout, "verify": verify_ssl}
    if method == "get":
        resp = requests.get(url, params=params, **kwargs)
    elif method == "post":
        resp = requests.post(url, params=params, json=json_body, **kwargs)
    else:
        return None, None, 400, f"unsupported method {method}"
    try:
        data = resp.json() if resp.content else {}
    except Exception:
        data = {"raw": resp.text[:1000]} if resp.content else {}
    return resp, data, resp.status_code, None


def _pn_aggregate(auth_info, pipeline, request_id="pendo-query", timeout=30, verify_ssl=True):
    root, err = _pn_root(None, auth_info)
    if err:
        return [], 400, err
    body = {
        "response": {"mimeType": "application/json"},
        "request": {
            "requestId": request_id,
            "name": request_id,
            "pipeline": pipeline,
        },
    }
    resp, data, status, err = _pn_request("post", root + "/aggregation", auth_info, json_body=body, timeout=timeout, verify_ssl=verify_ssl)
    if err:
        return [], 401, err
    if status >= 400:
        return [], status, _pn_err(resp)
    return _pn_results(data), status, "ok"


def _pn_match(record, query):
    q = str(query).lower()
    for key in ("id", "trackTypeId", "name", "event", "displayName", "track_type_id"):
        val = record.get(key)
        if val is not None and q in str(val).lower():
            return True
    return False


def _host_is(url, *domains):
    """True only if url's hostname equals or is a subdomain of one of domains."""
    from urllib.parse import urlparse
    u = str(url or "").strip()
    if "://" not in u:
        u = "https://" + u
    try:
        host = (urlparse(u).hostname or "").lower()
    except Exception:
        return False
    return any(host == d or host.endswith("." + d) for d in domains)
