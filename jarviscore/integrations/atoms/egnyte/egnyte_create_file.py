import requests
from typing import Any, Dict, List, Optional

# Egnyte File System API — https://developers.egnyte.com/docs/read/File_System_Management_API_Documentation
_EGNYTE_PUBAPI_SUFFIX = "/pubapi/v1"


def egnyte_create_file(auth_info: dict, payload: Dict[str, Any], timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Upload file (POST /pubapi/v1/fs-content/{path}). payload.file_path + content or local_path. Bearer OAuth per Egnyte Public API. Official: https://developers.egnyte.com/docs/read/File_System_Management_API_Documentation"""
    try:
        if not payload or not isinstance(payload, dict):
            return {"records": [], "data_count": 0, "status": 400, "message": "payload is required"}
        file_path = payload.get("file_path") or payload.get("path")
        if not file_path:
            return {"records": [], "data_count": 0, "status": 400, "message": "payload.file_path (or path) is required"}
        api, err = _egnyte_api_root(base_url)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err}
        content = payload.get("content")
        local_path = payload.get("local_path")
        if content is None and local_path:
            try:
                with open(str(local_path), "rb") as handle:
                    content = handle.read()
            except OSError as exc:
                return {"records": [], "data_count": 0, "status": 400, "message": str(exc)}
        if content is None:
            return {"records": [], "data_count": 0, "status": 400, "message": "payload.content or payload.local_path is required"}
        if isinstance(content, str):
            content = content.encode("utf-8")
        headers, auth_err = _egnyte_auth(auth_info, content=True)
        if auth_err:
            return {"records": [], "data_count": 0, "status": 401, "message": auth_err}
        resp = requests.post(
            _egnyte_fs_content_url(api, str(file_path)),
            headers=headers,
            data=content,
            timeout=timeout,
            verify=verify_ssl,
        )
        if resp.status_code >= 400:
            return {"records": [], "data_count": 0, "status": resp.status_code, "message": resp.text[:1000]}
        data = resp.json() if resp.text else {"path": file_path}
        records = [data] if isinstance(data, dict) else [{"path": file_path}]
        prov = _egnyte_provision_id(data) or [str(file_path)]
        return {
            "records": records,
            "data_count": len(records),
            "status": resp.status_code,
            "message": "ok",
            "provision_ids": prov,
        }
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


def _egnyte_fs_content_url(api: str, path: str) -> str:
    return _egnyte_fs_url(api, path).replace("/fs/", "/fs-content/", 1)


def _egnyte_provision_id(data: Any) -> List[str]:
    if not isinstance(data, dict):
        return []
    for key in ("entry_id", "group_id", "folder_id", "path"):
        val = data.get(key)
        if val not in (None, ""):
            return [str(val)]
    return []
