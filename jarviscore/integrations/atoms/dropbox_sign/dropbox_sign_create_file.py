import requests
from typing import Any, Dict, List, Optional

# Dropbox Sign API v3 — https://developers.hellosign.com/api/reference/signature_request_send
SIGN_API = "https://api.hellosign.com/v3"


def dropbox_sign_create_file(auth_info: dict, payload: Dict[str, Any], timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Send signature request (multipart form). Basic API key or Bearer OAuth. Official: https://developers.hellosign.com/api/signature-request/send"""
    try:
        if not payload:
            return {
                "records": [],
                "data_count": 0,
                "status": 400,
                "message": "payload is required (HelloSign /signature_request/send form fields)",
            }
        api, err = _sign_api_root(base_url)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err}
        headers, basic, auth_err = _sign_auth(auth_info)
        if auth_err:
            return {"records": [], "data_count": 0, "status": 401, "message": auth_err}
        form_data: List[Any] = []
        files: List[Any] = []
        for key, value in payload.items():
            if key == "file_paths" and isinstance(value, list):
                for path in value:
                    files.append(("file", open(str(path), "rb")))
                continue
            if isinstance(value, (list, tuple)):
                for item in value:
                    form_data.append((key, str(item)))
            elif value is not None:
                form_data.append((key, str(value)))
        resp = requests.post(
            f"{api}/signature_request/send",
            headers=headers,
            auth=basic,
            data=form_data,
            files=files or None,
            timeout=timeout,
            verify=verify_ssl,
        )
        for _, handle in files:
            handle.close()
        if resp.status_code >= 400:
            return {"records": [], "data_count": 0, "status": resp.status_code, "message": resp.text[:1000]}
        data = resp.json() if resp.text else {}
        records = _sign_single_signature_request(data)
        prov: List[str] = []
        if records:
            sid = records[0].get("signature_request_id") or records[0].get("id")
            if sid:
                prov = [str(sid)]
        return {
            "records": records,
            "data_count": len(records),
            "status": resp.status_code,
            "message": "ok",
            "provision_ids": prov,
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


def _sign_single_signature_request(data: Any) -> List[Dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    block = data.get("signature_request")
    if isinstance(block, dict):
        return [block]
    if data.get("signature_request_id"):
        return [data]
    return []
