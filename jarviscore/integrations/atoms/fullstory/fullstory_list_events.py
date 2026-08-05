import requests
from typing import Any, Dict, List, Optional

# FullStory Server API — https://developer.fullstory.com/server/
_FS_API_HOST = "https://api.fullstory.com"


def fullstory_list_events(auth_info: dict, session_id: str, limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Get captured events for a session (GET .../sessions/{sessionId}/events). session_id is userId:sessionId. Authorization: Basic {api_key} from Settings > Integrations > API Keys (Architect for data reads). Official: https://developer.fullstory.com/"""
    try:
        if not session_id:
            return {"records": [], "data_count": 0, "status": 400, "message": "session_id is required"}
        api, err = _fs_api_root(base_url)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err}
        headers, auth_err = _fs_fullstory_auth(auth_info)
        if auth_err:
            return {"records": [], "data_count": 0, "status": 401, "message": auth_err}
        sid = _fs_pct_enc(str(session_id).strip())
        url = f"{api}/v2/sessions/{sid}/events"
        resp = requests.get(url, headers=headers, timeout=timeout, verify=verify_ssl)
        status = resp.status_code
        if status >= 400:
            return {"records": [], "data_count": 0, "status": status, "message": resp.text[:1000]}
        data = resp.json() if resp.text else {}
        records = _fs_results(data)
        if not records and isinstance(data, dict):
            events = data.get("events")
            if isinstance(events, list):
                records = [item for item in events if isinstance(item, dict)]
        cap = min(max(int(limit or 25), 1), 1000)
        records = records[:cap]
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


def _fs_pct_enc(text: str) -> str:
    out = []
    for ch in str(text):
        o = ord(ch)
        if o < 128 and (ch.isalnum() or ch in "-_.~"):
            out.append(ch)
        else:
            for b in ch.encode("utf-8"):
                out.append(f"%{b:02X}")
    return "".join(out)
