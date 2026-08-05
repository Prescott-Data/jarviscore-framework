import requests
from typing import Any, Dict, List, Optional

# Egnyte Search API v2 — https://developers.egnyte.com/docs/read/Search_API_Documentation (POST /pubapi/v2/search)
_EGNYTE_PUBAPI_SUFFIX = "/pubapi/v1"


def egnyte_search_records(auth_info: dict, query: str, limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Search files and folders (GET /pubapi/v1/search). Bearer OAuth per Egnyte Public API. Official: https://developers.egnyte.com/docs/read/Search_API_Documentation"""
    try:
        if not query:
            return {"records": [], "data_count": 0, "status": 400, "message": "query is required"}
        api, err = _egnyte_api_root(base_url)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err}
        headers, auth_err = _egnyte_auth(auth_info, json_body=True)
        if auth_err:
            return {"records": [], "data_count": 0, "status": 401, "message": auth_err}
        search_url = f"{api.replace(_EGNYTE_PUBAPI_SUFFIX, '/pubapi/v2')}/search"
        cap = min(max(int(limit or 25), 1), 1000)
        records: List[Dict[str, Any]] = []
        offset = 0
        status = 0
        while len(records) < cap:
            count = min(cap - len(records), 100)
            body = {"query": query, "count": count, "offset": offset}
            resp = requests.post(
                search_url,
                headers=headers,
                json=body,
                timeout=timeout,
                verify=verify_ssl,
            )
            status = resp.status_code
            if status >= 400:
                return {"records": records, "data_count": len(records), "status": status, "message": resp.text[:1000]}
            data = resp.json() if resp.text else {}
            batch = data.get("results") if isinstance(data, dict) else []
            if not isinstance(batch, list):
                batch = []
            for item in batch:
                if isinstance(item, dict):
                    records.append(item)
                    if len(records) >= cap:
                        return {"records": records[:cap], "data_count": len(records[:cap]), "status": status, "message": "ok"}
            if len(batch) < count:
                break
            offset += count
            if offset > 100000:
                break
        return {"records": records[:cap], "data_count": len(records[:cap]), "status": status, "message": "ok"}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}



def _egnyte_api_root(base_url: str):
    root = (base_url or "").rstrip("/")
    if not root:
        return None, "base_url is required (https://{domain}.egnyte.com/pubapi/v1)"
    if _EGNYTE_PUBAPI_SUFFIX not in root:
        return None, "base_url must be the Egnyte pubapi v1 root (https://{domain}.egnyte.com/pubapi/v1)"
    return root, None


def _egnyte_auth(auth_info: Optional[Dict[str, Any]], json_body: bool = False, content: bool = False):
    auth_info = auth_info or {}
    headers: Dict[str, str] = {"Accept": "application/json"}
    if json_body:
        headers["Content-Type"] = "application/json"
    elif content:
        headers["Content-Type"] = "application/octet-stream"
    token = auth_info.get("access_token")
    if not token:
        return None, "auth_info requires access_token"
    tok = str(token).strip()
    headers["Authorization"] = tok if tok.lower().startswith("bearer ") else f"Bearer {tok}"
    return headers, None
