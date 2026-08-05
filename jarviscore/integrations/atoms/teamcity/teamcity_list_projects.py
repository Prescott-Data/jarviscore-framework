import requests
from typing import Any, Dict, List, Optional

def teamcity_list_projects(auth_info: dict, limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """TeamCity REST: list projects. Official: https://www.jetbrains.com/help/teamcity/rest/teamcity-rest.html"""
    try:
        root, err = _tc_root(base_url, auth_info)
        if err: return _tc_dataset([], 400, err)
        headers, aerr = _tc_auth(auth_info)
        if aerr: return _tc_dataset([], 401, aerr)
        resp = requests.get(f"{root}/projects", headers=headers, params={"locator": f"count:{limit}"}, timeout=timeout, verify=verify_ssl)
        if resp.status_code >= 400: return _tc_dataset([], resp.status_code, _tc_err(resp))
        data = resp.json() if resp.content else {}
        return _tc_dataset(_tc_items(data, "project"), resp.status_code, "ok")
    except Exception as e: return _tc_dataset([], 500, str(e))

# TeamCity REST API — Official: https://www.jetbrains.com/help/teamcity/rest/teamcity-rest.html


def _tc_root(base_url, auth_info):
    auth_info = auth_info or {}
    root = (base_url or auth_info.get("teamcity_url") or auth_info.get("base_url") or "").strip().rstrip("/")
    if not root:
        return None, "base_url is required (https://teamcity.example.com)"
    if not root.endswith("/app/rest"):
        root = root + "/app/rest" if "/app/" not in root else root
    return root, None


def _tc_auth(auth_info):
    auth_info = auth_info or {}
    token = auth_info.get("access_token")
    if not token:
        return None, "auth_info.access_token is required"
    tok = str(token).strip()
    return {"Accept": "application/json", "Authorization": tok if tok.lower().startswith("bearer ") else f"Bearer {tok}"}, None


def _tc_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _tc_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get("id") or fallback_id
    ids = [pid] if pid not in (None, "") else []
    rec = obj if obj else ({"id": pid} if ids else {})
    return {"records": [rec] if rec else [], "data_count": 1 if rec else 0, "status": status, "message": msg, "provision_ids": ids}


def _tc_err(resp):
    return (resp.text or f"HTTP {resp.status_code}")[:1000]


def _tc_items(data, key):
    if isinstance(data, dict):
        block = data.get(key) or data.get(key.rstrip("s"))
        if isinstance(block, list):
            return [x for x in block if isinstance(x, dict)]
        if isinstance(block, dict):
            return [block]
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    return []
