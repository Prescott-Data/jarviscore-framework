import requests
from typing import Any, Dict, List, Optional

def streak_list_contacts(auth_info: dict, team_key: str, limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Streak API: list contacts. Official: https://streak.com/api#get_contacts_in_pipeline"""
    try:
        if not team_key: return _st_dataset([], 400, "team_key is required")
        root, _ = _st_root(base_url, auth_info)
        root_v2 = root[:-3] + "/v2" if root.endswith("/v1") else root
        headers, err = _st_auth(auth_info)
        if err: return _st_dataset([], 401, err)
        # Contacts are team-scoped v2: GET /api/v2/teams/{teamKey}/contacts.
        resp = requests.get(root_v2 + f"/teams/{team_key}/contacts", headers=headers, timeout=timeout, verify=verify_ssl)
        try: data = resp.json() if resp.content else []
        except Exception: data = []
        if resp.status_code >= 400: return _st_dataset([], resp.status_code, _st_err(resp))
        records = [x for x in (data if isinstance(data, list) else []) if isinstance(x, dict)][:_st_cap(limit)]
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
