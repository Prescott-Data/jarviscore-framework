import requests
from typing import Any, Dict, List, Optional


def sourceforge_get_project(auth_info: dict, project: str, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """SourceForge REST: get project overview. Official: https://sourceforge.net/p/forge/documentation/REST%20API/"""
    try:
        if not project:
            return _sf_dataset([], 400, "project is required")
        root, _ = _sf_root(base_url, auth_info)
        headers, err = _sf_auth(auth_info)
        if err:
            return _sf_dataset([], 401, err)
        slug = str(project).strip().strip("/")
        resp = requests.get(f"{root}/rest/p/{slug}/", headers=headers, timeout=timeout, verify=verify_ssl)
        try:
            data = resp.json() if resp.content else {}
        except Exception:
            data = {}
        if resp.status_code >= 400:
            return _sf_dataset([], resp.status_code, _sf_err(resp))
        return _sf_dataset([data] if isinstance(data, dict) else [], resp.status_code, "ok")
    except Exception as e:
        return _sf_dataset([], 500, str(e))


# SourceForge Allura REST API — Official docs: https://sourceforge.net/p/forge/documentation/REST%20API/


def _sf_root(base_url, auth_info):
    auth_info = auth_info or {}
    root = (base_url or auth_info.get("sourceforge_url") or auth_info.get("base_url") or "https://sourceforge.net").strip().rstrip("/")
    return root, None


def _sf_auth(auth_info):
    auth_info = auth_info or {}
    token = auth_info.get("access_token")
    if not token:
        return None, "auth_info.access_token is required"
    t = str(token).strip()
    return {"Accept": "application/json", "Authorization": t if t.lower().startswith("bearer ") else f"Bearer {t}"}, None


def _sf_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _sf_err(resp):
    return (resp.text or f"HTTP {resp.status_code}")[:1000]
