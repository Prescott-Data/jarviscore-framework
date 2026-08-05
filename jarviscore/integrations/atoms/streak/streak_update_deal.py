import requests
from typing import Any, Dict, List, Optional

def streak_update_deal(auth_info: dict, box_key: str, payload: Dict[str, Any], timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Streak API: update deal. Official: https://streak.com/api#update_a_box"""
    try:
        if not box_key: return _st_provision({}, 400, "box_key is required")
        if not isinstance(payload, dict) or not payload: return _st_provision({}, 400, "payload is required")
        root, _ = _st_root(base_url, auth_info)
        headers, err = _st_auth(auth_info)
        if err: return _st_provision({}, 401, err)
        headers["Content-Type"] = "application/json"
        resp = requests.post(root + "/boxes/" + str(box_key), headers=headers, json=payload, timeout=timeout, verify=verify_ssl)
        try: data = resp.json() if resp.content else {}
        except Exception: data = {}
        if resp.status_code >= 400: return _st_provision(data if isinstance(data, dict) else {}, resp.status_code, _st_err(resp))
        return _st_provision(data if isinstance(data, dict) else {}, resp.status_code, "ok", fallback_id=box_key)
    except Exception as e: return _st_provision({}, 500, str(e))


# Streak API — Official docs: https://streak.com/api


def _st_root(base_url, auth_info):
    auth_info = auth_info or {}
    root = (base_url or auth_info.get("streak_url") or auth_info.get("base_url") or "https://www.streak.com/api/v1").strip().rstrip("/")
    if not root.endswith("/v1"):
        if "streak.com" in root and "/v1" not in root:
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
