import requests
from typing import Any, Dict, List, Optional

# Google People API — https://developers.google.com/people/api/rest
_PEOPLE_API_ROOT = "https://people.googleapis.com/v1"


def google_people_get_user_profile(auth_info: dict, person_fields: str = "names,emailAddresses,phoneNumbers,organizations", timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Get the authenticated user's People profile. Official: https://developers.google.com/people/api/rest/v1/people/get"""
    try:
        api, err = _people_api_root(base_url)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err}
        headers, auth_err = _people_auth(auth_info)
        if auth_err:
            return {"records": [], "data_count": 0, "status": 401, "message": auth_err}
        url = f"{api}/people/me"
        resp = requests.get(url, headers=headers, params={"personFields": person_fields}, timeout=timeout, verify=verify_ssl)
        status = resp.status_code
        if status >= 400:
            return {"records": [], "data_count": 0, "status": status, "message": resp.text[:1000]}
        data = resp.json() if resp.text else {}
        records = [data] if isinstance(data, dict) and data else []
        return {"records": records, "data_count": len(records), "status": status, "message": "ok"}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}



def _people_api_root(base_url: str):
    root = (base_url or _PEOPLE_API_ROOT).rstrip("/")
    if "people.googleapis.com" not in root:
        return None, "base_url must be People API root (https://people.googleapis.com/v1)"
    return root, None


def _people_auth(auth_info: Optional[Dict[str, Any]]) -> tuple:
    auth_info = auth_info or {}
    headers = {"Accept": "application/json"}
    token = auth_info.get("access_token")
    if not token:
        return None, "auth_info requires access_token"
    tok = str(token).strip()
    headers["Authorization"] = tok if tok.lower().startswith("bearer ") else f"Bearer {tok}"
    return headers, None


def _people_page(url: str, headers: Dict[str, str], params: Dict[str, Any], item_key: str, limit: int, timeout: int, verify_ssl: bool) -> tuple:
    records: List[Dict[str, Any]] = []
    cap = min(max(int(limit or 25), 1), 1000)
    page_token = None
    status = 0
    while len(records) < cap:
        q = dict(params)
        q["pageSize"] = min(100, cap - len(records))
        if page_token:
            q["pageToken"] = page_token
        resp = requests.get(url, headers=headers, params=q, timeout=timeout, verify=verify_ssl)
        status = resp.status_code
        if status >= 400:
            return records, status, resp.text[:1000]
        data = resp.json() if resp.text else {}
        items = data.get(item_key) if isinstance(data, dict) else None
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    records.append(item)
                    if len(records) >= cap:
                        break
        page_token = data.get("nextPageToken") if isinstance(data, dict) else None
        if not page_token or len(records) >= cap:
            break
    return records, status, "ok"
