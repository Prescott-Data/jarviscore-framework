import requests
from typing import Any, Dict, List, Optional

# Egnyte File System API — https://developers.egnyte.com/docs/read/File_System_Management_API_Documentation
_EGNYTE_PUBAPI_SUFFIX = "/pubapi/v1"


def egnyte_list_folders(auth_info: dict, folder_path: str = "/Shared", limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """List subfolders (GET /pubapi/v1/fs/{folder_path}?list_content=true, folders[]). Bearer OAuth per Egnyte Public API. Official: https://developers.egnyte.com/docs/read/File_System_Management_API_Documentation"""
    try:
        api, err = _egnyte_api_root(base_url)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err}
        headers, auth_err = _egnyte_auth(auth_info)
        if auth_err:
            return {"records": [], "data_count": 0, "status": 401, "message": auth_err}
        records, status, message = _egnyte_list_entries(
            api, headers, folder_path, limit, "folders", timeout, verify_ssl
        )
        if message != "ok":
            return {"records": records, "data_count": len(records), "status": status, "message": message}
        return {"records": records, "data_count": len(records), "status": status, "message": "ok"}
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


def _egnyte_pct_enc(text: str) -> str:
    out = []
    for ch in str(text):
        o = ord(ch)
        if o < 128 and (ch.isalnum() or ch in "-_.~"):
            out.append(ch)
        else:
            for b in ch.encode("utf-8"):
                out.append(f"%{b:02X}")
    return "".join(out)


def _egnyte_fs_url(api: str, path: str) -> str:
    raw = str(path or "/")
    if not raw.startswith("/"):
        raw = "/" + raw
    parts = [p for p in raw.split("/") if p]
    if not parts:
        return f"{api}/fs/"
    return f"{api}/fs/" + "/".join(_egnyte_pct_enc(p) for p in parts)


def _egnyte_list_entries(api, headers, folder_path, limit, item_key, timeout, verify_ssl):
    records: List[Dict[str, Any]] = []
    cap = min(max(int(limit or 25), 1), 1000)
    offset = 0
    status = 0
    while len(records) < cap:
        count = min(cap - len(records), 100)
        params = {"list_content": "true", "count": count, "offset": offset}
        resp = requests.get(
            _egnyte_fs_url(api, folder_path),
            headers=headers,
            params=params,
            timeout=timeout,
            verify=verify_ssl,
        )
        status = resp.status_code
        if status >= 400:
            return records, status, resp.text[:1000]
        data = resp.json() if resp.text else {}
        batch = data.get(item_key) if isinstance(data, dict) else []
        if not isinstance(batch, list):
            batch = []
        for item in batch:
            if isinstance(item, dict):
                records.append(item)
                if len(records) >= cap:
                    return records[:cap], status, "ok"
        if len(batch) < count:
            break
        offset += count
        if offset > 100000:
            break
    return records[:cap], status, "ok"
