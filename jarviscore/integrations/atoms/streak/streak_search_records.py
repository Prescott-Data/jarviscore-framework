import requests
from typing import Any, Dict, List, Optional

def streak_search_records(auth_info: dict, query: str, pipeline_key: str = "", limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Streak API: search boxes in pipeline client-side. Official: https://streak.com/api#get_boxes_in_pipeline"""
    try:
        if not query: return _st_dataset([], 400, "query is required")
        auth_info = auth_info or {}
        root, _ = _st_root(base_url, auth_info)
        headers, err = _st_auth(auth_info)
        if err: return _st_dataset([], 401, err)
        # Streak global search: GET /api/v1/search?query= (optionally scoped by pipelineKey).
        params = {"query": str(query)}
        pk = pipeline_key or auth_info.get("pipeline_key")
        if pk:
            params["pipelineKey"] = pk
        resp = requests.get(root + "/search", headers=headers, params=params, timeout=timeout, verify=verify_ssl)
        try: data = resp.json() if resp.content else {}
        except Exception: data = {}
        if resp.status_code >= 400: return _st_dataset([], resp.status_code, _st_err(resp))
        records = _st_search_results(data)[:_st_cap(limit)]
        return _st_dataset(records, resp.status_code, "ok")
    except Exception as e: return _st_dataset([], 500, str(e))


# Streak API — Official docs: https://streak.com/api


def _st_root(base_url, auth_info):
    auth_info = auth_info or {}
    root = (base_url or auth_info.get("streak_url") or auth_info.get("base_url") or "https://www.streak.com/api/v1").strip().rstrip("/")
    if not root.endswith("/v1"):
        if _host_is(root, "streak.com") and "/v1" not in root:
            root = root + "/api/v1" if "/api" not in root else root + "/v1"
    return root, None


def _st_auth(auth_info):
    auth_info = auth_info or {}
    api_key = auth_info.get("api_key")
    if not api_key:
        return None, "auth_info.api_key is required"
    import base64
    creds = base64.b64encode(f"{str(api_key).strip()}:".encode()).decode()
    return {"Accept": "application/json", "Authorization": f"Basic {creds}"}, None


def _st_cap(limit):
    return min(max(int(limit or 25), 1), 1000)


def _st_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _st_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get("key") or obj.get("boxKey") or obj.get("contactKey") or obj.get("pipelineKey") or fallback_id
    ids = [pid] if pid not in (None, "") else []
    rec = obj if obj else ({"id": pid} if ids else {})
    return {"records": [rec] if rec else [], "data_count": 1 if rec else 0, "status": status, "message": msg, "provision_ids": ids}


def _st_err(resp):
    return (resp.text or f"HTTP {resp.status_code}")[:1000]

def _st_search_results(data):
    # Search returns boxes/contacts/organizations; flatten any lists found.
    out = []
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        results = data.get("results") if isinstance(data.get("results"), (dict, list)) else data
        if isinstance(results, list):
            return [x for x in results if isinstance(x, dict)]
        if isinstance(results, dict):
            for key in ("boxes", "contacts", "organizations"):
                val = results.get(key)
                if isinstance(val, list):
                    out.extend([x for x in val if isinstance(x, dict)])
    return out


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
