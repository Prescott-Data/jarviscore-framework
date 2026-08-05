import requests
from typing import Any, Dict, List, Optional

# FullStory Server API — https://developer.fullstory.com/server/
_FS_API_HOST = "https://api.fullstory.com"


def fullstory_search_records(auth_info: dict, uid: Optional[str] = None, email: Optional[str] = None, display_name: Optional[str] = None, limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Search users by uid, email, or display_name (GET /v2/users). page_token pagination, response.results[]. Authorization: Basic {api_key} from Settings > Integrations > API Keys (Architect for data reads). Official: https://developer.fullstory.com/"""
    try:
        if not any([uid, email, display_name]):
            return {"records": [], "data_count": 0, "status": 400, "message": "At least one of uid, email, or display_name is required"}
        api, err = _fs_api_root(base_url)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err}
        headers, auth_err = _fs_fullstory_auth(auth_info)
        if auth_err:
            return {"records": [], "data_count": 0, "status": 401, "message": auth_err}
        params: Dict[str, Any] = {}
        if uid:
            params["uid"] = uid
        if email:
            params["email"] = email
        if display_name:
            params["display_name"] = display_name
        records, status, message = _fs_paginate_users(f"{api}/v2/users", headers, limit, timeout, verify_ssl, params)
        if message != "ok":
            return {"records": records, "data_count": len(records), "status": status, "message": message}
        return {"records": records, "data_count": len(records), "status": status, "message": "ok"}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}



def _fs_api_root(base_url: str):
    root = (base_url or _FS_API_HOST).rstrip("/")
    if not root:
        return None, "base_url is required (https://api.fullstory.com)"
    if "fullstory.com" not in root:
        return None, "base_url must be the FullStory API host (https://api.fullstory.com)"
    return root, None


def _fs_fullstory_auth(auth_info, json_body: bool = False):
    auth_info = auth_info or {}
    headers = {"Accept": "application/json"}
    if json_body:
        headers["Content-Type"] = "application/json"
    key = auth_info.get("api_key")
    if not key:
        return None, "auth_info requires api_key or access_token"
    tok = str(key).strip()
    headers["Authorization"] = tok if tok.lower().startswith("basic ") else "Basic " + tok
    return headers, None


def _fs_results(data):
    if isinstance(data, dict):
        batch = data.get("results")
        if isinstance(batch, list):
            return [item for item in batch if isinstance(item, dict)]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _fs_paginate_users(url, headers, limit, timeout, verify_ssl, params):
    records = []
    cap = min(max(int(limit or 25), 1), 1000)
    page_token = None
    status = 0
    while len(records) < cap:
        q = dict(params)
        if page_token:
            q["page_token"] = page_token
        resp = requests.get(url, headers=headers, params=q, timeout=timeout, verify=verify_ssl)
        status = resp.status_code
        if status >= 400:
            return records, status, resp.text[:1000]
        data = resp.json() if resp.text else {}
        batch = _fs_results(data)
        for item in batch:
            records.append(item)
            if len(records) >= cap:
                return records[:cap], status, "ok"
        page_token = data.get("next_page_token") if isinstance(data, dict) else None
        if not page_token or not batch:
            break
    return records[:cap], status, "ok"
