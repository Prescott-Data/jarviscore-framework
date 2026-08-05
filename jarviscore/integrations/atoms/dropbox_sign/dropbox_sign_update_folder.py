import requests
from typing import Any, Dict, List, Optional

# Dropbox Sign API v3 — https://developers.hellosign.com/api/reference/template_update_files
SIGN_API = "https://api.hellosign.com/v3"


def dropbox_sign_update_folder(auth_info: dict, folder_id: str, payload: Dict[str, Any], timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Update template files overlay. Official: https://developers.hellosign.com/api/template/update-files"""
    try:
        if not folder_id or not payload:
            return {"records": [], "data_count": 0, "status": 400, "message": "folder_id and payload are required"}
        api, err = _sign_api_root(base_url)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err}
        headers, basic, auth_err = _sign_auth(auth_info, json_body=True)
        if auth_err:
            return {"records": [], "data_count": 0, "status": 401, "message": auth_err}
        resp = requests.post(
            f"{api}/template/update_files/{folder_id}",
            headers=headers,
            auth=basic,
            json=payload,
            timeout=timeout,
            verify=verify_ssl,
        )
        if resp.status_code >= 400:
            return {"records": [], "data_count": 0, "status": resp.status_code, "message": resp.text[:1000]}
        data = resp.json() if resp.text else {}
        records = _sign_single_template(data)
        return {
            "records": records,
            "data_count": len(records),
            "status": resp.status_code,
            "message": "ok",
            "provision_ids": [folder_id],
        }
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}



def _sign_api_root(base_url: str):
    root = (base_url or SIGN_API).rstrip("/")
    if root.endswith("/v3"):
        return root, None
    if "hellosign.com" in root or "dropboxsign.com" in root:
        if "/v3" not in root:
            if root.endswith("/v1"):
                root = root[:-3] + "/v3"
            elif root.endswith("/api"):
                root = root + "/v3"
            else:
                root = f"{root}/v3"
        return root, None
    return None, "base_url must be Dropbox Sign API v3 root (https://api.hellosign.com/v3)"


def _sign_auth(auth_info: Optional[Dict[str, Any]], json_body: bool = False):
    auth_info = auth_info or {}
    headers = {"Accept": "application/json"}
    if json_body:
        headers["Content-Type"] = "application/json"
    api_key = auth_info.get("api_key")
    if not api_key:
        return None, None, "auth_info.api_key is required"
    return headers, (str(api_key).strip(), ""), None


def _sign_single_template(data: Any) -> List[Dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    block = data.get("template")
    if isinstance(block, dict):
        return [block]
    if data.get("template_id"):
        return [data]
    return []
