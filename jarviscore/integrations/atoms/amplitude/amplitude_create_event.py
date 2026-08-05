import requests
from typing import Any, Dict, List, Optional


# POST /2/httpapi — https://www.docs.developers.amplitude.com/analytics/apis/http-v2-api/
# Auth: api_key in JSON body (project API key)


def amplitude_create_event(auth_info: dict, payload: Dict[str, Any], timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Ingest analytics events (POST https://api2.amplitude.com/2/httpapi). Official: https://www.docs.developers.amplitude.com/analytics/apis/http-v2-api/"""
    try:
        if not base_url:
            return _amp_provision([], 400, "base_url is required")
        if not isinstance(payload, dict) or not payload:
            return _amp_provision([], 400, "payload must be a non-empty dict")
        _, dash_host, root_err = _amp_dashboard_root(base_url)
        if root_err:
            return _amp_provision([], 400, root_err)
        api_key = _amp_api_key(auth_info)
        if not api_key:
            return _amp_provision([], 401, "auth_info.api_key is required for event ingestion")
        events = payload.get("events") if isinstance(payload.get("events"), list) else [payload]
        body = {"api_key": str(api_key), "events": events}
        url = f"{_amp_ingest_root(dash_host)}/2/httpapi"
        resp = requests.post(url, json=body, timeout=timeout, verify=verify_ssl)
        status = resp.status_code
        try:
            data = resp.json() if resp.content else {}
        except Exception:
            data = {"message": resp.text[:1000]}
        if status >= 400:
            return _amp_provision([], status, _amp_msg(data) or _amp_err(resp))
        rec = data if isinstance(data, dict) else {}
        ids = _amp_event_provision_ids(events)
        return _amp_provision([rec] if rec else [], status, "ok", ids)

    except Exception as e:
        return _amp_provision([], 500, str(e))


def _pct_enc(text, safe=""):
    out = []
    for ch in str(text):
        o = ord(ch)
        if ch in safe or (o < 128 and (ch.isalnum() or ch in "-_.~")):
            out.append(ch)
        else:
            for b in ch.encode("utf-8"):
                out.append(f"%{b:02X}")
    return "".join(out)


def _parse_url(url):
    scheme, rest = ("", url)
    if "://" in url:
        scheme, rest = url.split("://", 1)
    fragment = ""
    if "#" in rest:
        rest, fragment = rest.split("#", 1)
    query = ""
    if "?" in rest:
        rest, query = rest.split("?", 1)
    if "/" in rest:
        netloc, path = rest.split("/", 1)
        path = "/" + path
    else:
        netloc, path = rest, "/"
    return scheme, netloc, path, query, fragment


def _build_url(scheme, netloc, path, query="", fragment=""):
    url = f"{scheme}://{netloc}{path or '/'}"
    if query:
        url += "?" + query
    if fragment:
        url += "#" + fragment
    return url


def _query_pairs(query):
    pairs = []
    for part in (query or "").split("&"):
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
        else:
            k, v = part, ""
        pairs.append((k, v))
    return pairs


def _query_get(url, name):
    _, _, _, query, _ = _parse_url(url)
    for k, v in _query_pairs(query):
        if k == name:
            return v
    return None


def _urlencode(params):
    return "&".join(f"{_pct_enc(str(k))}={_pct_enc(str(v))}" for k, v in params.items())


def _json_escape(value):
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def _json_dumps(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return f'"{_json_escape(value)}"'
    if isinstance(value, dict):
        parts = [f'"{_json_escape(k)}": {_json_dumps(v)}' for k, v in value.items()]
        return "{" + ", ".join(parts) + "}"
    if isinstance(value, list):
        return "[" + ", ".join(_json_dumps(v) for v in value) + "]"
    return f'"{_json_escape(str(value))}"'


def _basename(path):
    p = str(path).replace("\\", "/")
    return p.rsplit("/", 1)[-1] if p else ""


def _guess_mime(path):
    ext = _basename(path).rsplit(".", 1)[-1].lower() if "." in _basename(path) else ""
    return {
        "pdf": "application/pdf",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "txt": "text/plain",
        "csv": "text/csv",
        "json": "application/json",
        "html": "text/html",
        "xml": "application/xml",
        "zip": "application/zip",
    }.get(ext, "application/octet-stream")

# Amplitude APIs — https://amplitude.com/docs/apis/analytics/dashboard-rest
# Dashboard REST (read): https://amplitude.com/api/2  (EU: https://analytics.eu.amplitude.com/api/2)
# Ingestion (write): https://api2.amplitude.com  (EU: https://api.eu.amplitude.com)
_AMP_DASHBOARD_SUFFIX = "/api/2"
_AMP_DASHBOARD_HOSTS = {
    "https://amplitude.com",
    "https://analytics.eu.amplitude.com",
}
_AMP_INGEST_HOSTS = {
    "https://amplitude.com": "https://api2.amplitude.com",
    "https://analytics.eu.amplitude.com": "https://api.eu.amplitude.com",
}


def _amp_dashboard_root(base_url: str):
    root = base_url.rstrip("/")
    if not root.endswith(_AMP_DASHBOARD_SUFFIX):
        return None, None, (
            "base_url must be https://amplitude.com/api/2 or "
            "https://analytics.eu.amplitude.com/api/2"
        )
    host = root[: -len(_AMP_DASHBOARD_SUFFIX)]
    if host not in _AMP_DASHBOARD_HOSTS:
        return None, None, (
            "base_url must be https://amplitude.com/api/2 or "
            "https://analytics.eu.amplitude.com/api/2"
        )
    return root, host, None


def _amp_ingest_root(dashboard_host: str) -> str:
    return _AMP_INGEST_HOSTS.get(dashboard_host, "https://api2.amplitude.com")


def _amp_basic_auth(auth_info):
    auth_info = auth_info or {}
    username = auth_info.get("username")
    password = auth_info.get("password")
    if not username or not password:
        return None, "auth_info requires username and password"
    return (str(username), str(password)), None


def _amp_api_key(auth_info):
    auth_info = auth_info or {}
    return auth_info.get("username")


def _amp_provision(records, status, msg, provision_ids=None):
    recs = records if isinstance(records, list) else []
    ids = provision_ids if isinstance(provision_ids, list) else []
    return {
        "records": recs,
        "data_count": len(recs),
        "status": status,
        "message": msg,
        "provision_ids": ids,
    }


def _amp_err(resp):
    return (resp.text if resp is not None else "request failed")[:1000]


def _amp_msg(data):
    if isinstance(data, dict):
        err = data.get("error") or data.get("message")
        if err:
            return str(err)[:1000]
    return str(data)[:1000] if data else "request failed"


def _amp_event_provision_ids(events):
    ids = []
    for ev in events if isinstance(events, list) else []:
        if not isinstance(ev, dict):
            continue
        iid = ev.get("insert_id") or ev.get("$insert_id")
        if iid not in (None, ""):
            ids.append(str(iid))
    return ids


def _amp_get_json(url, auth_info, params=None, timeout=30, verify_ssl=True):
    auth, auth_err = _amp_basic_auth(auth_info)
    if auth_err:
        return None, 400, auth_err
    resp = requests.get(url, auth=auth, params=params, timeout=timeout, verify=verify_ssl)
    status = resp.status_code
    if status >= 400:
        return None, status, resp.text[:1000]
    try:
        return resp.json(), status, "ok"
    except Exception:
        return None, status, "Unexpected response format"


def _amp_event_rows(data):
    if isinstance(data, dict):
        rows = data.get("data")
        if isinstance(rows, list):
            return rows
    if isinstance(data, list):
        return data
    return []


def _amp_match_event(row, event_id: str) -> bool:
    if not isinstance(row, dict):
        return False
    target = str(event_id).strip().lower()
    for key in ("value", "display", "id", "event_type"):
        val = row.get(key)
        if val is not None and str(val).strip().lower() == target:
            return True
    return False


def _amp_match_query(row, query: str) -> bool:
    if not query:
        return True
    needle = query.lower()
    if not isinstance(row, dict):
        return False
    for key in ("value", "display", "event_type", "id"):
        val = row.get(key)
        if val is not None and needle in str(val).lower():
            return True
    return False
