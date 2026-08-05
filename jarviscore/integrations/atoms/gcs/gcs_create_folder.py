import requests
from typing import Any, Dict, List, Optional

# Google Cloud Storage JSON API — https://cloud.google.com/storage/docs/json_api
_GCS_API_ROOT = "https://storage.googleapis.com/storage/v1"
_GCS_UPLOAD_ROOT = "https://storage.googleapis.com/upload/storage/v1"


def gcs_create_folder(auth_info: dict, bucket_name: str, folder_path: str, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Create folder placeholder object (zero-byte object with trailing / name). OAuth Bearer token (cloud-platform or devstorage scope). JSON API root required. Official: https://cloud.google.com/storage/docs/json_api/v1"""
    try:
        if not folder_path:
            return {"records": [], "data_count": 0, "status": 400, "message": "folder_path is required"}
        folder = _gcs_norm_prefix(folder_path)
        if not folder:
            return {"records": [], "data_count": 0, "status": 400, "message": "folder_path is required"}
        api, upload_api, err = _gcs_api_root(base_url)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err}
        bucket, err = _gcs_bucket(bucket_name, auth_info)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err}
        headers, auth_err = _gcs_auth(auth_info, content_type="application/x-www-form-urlencoded;charset=UTF-8")
        if auth_err:
            return {"records": [], "data_count": 0, "status": 401, "message": auth_err}
        params = {"uploadType": "media", "name": folder}
        resp = requests.post(
            f"{upload_api}/b/{_gcs_pct_enc(bucket)}/o",
            headers=headers,
            params=params,
            data=b"",
            timeout=timeout,
            verify=verify_ssl,
        )
        status = resp.status_code
        data = resp.json() if resp.text else {}
        if status >= 400:
            return {"records": [], "data_count": 0, "status": status, "message": resp.text[:1000]}
        records = [data] if isinstance(data, dict) and data else [{"name": folder, "prefix": folder}]
        return {
            "records": records,
            "data_count": len(records),
            "status": status,
            "message": "ok",
            "provision_ids": [folder],
        }
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}



def _gcs_api_root(base_url: str):
    root = (base_url or _GCS_API_ROOT).rstrip("/")
    if not root:
        return None, None, "base_url is required (https://storage.googleapis.com/storage/v1)"
    if "storage.googleapis.com" not in root or not root.endswith("/storage/v1"):
        return None, None, "base_url must be the GCS JSON API root (https://storage.googleapis.com/storage/v1)"
    upload = root.replace("/storage/v1", "/upload/storage/v1")
    return root, upload, None


def _gcs_bucket(bucket_name, auth_info):
    auth_info = auth_info or {}
    bucket = bucket_name or auth_info.get("bucket") or auth_info.get("bucket_name")
    if bucket in (None, ""):
        return None, "bucket_name is required (or auth_info.bucket)"
    return str(bucket).strip(), None


def _gcs_auth(auth_info, json_body: bool = False, content_type: Optional[str] = None):
    auth_info = auth_info or {}
    headers = {"Accept": "application/json"}
    if json_body:
        headers["Content-Type"] = "application/json"
    elif content_type:
        headers["Content-Type"] = content_type
    token = auth_info.get("access_token")
    if not token:
        return None, "auth_info requires access_token"
    tok = str(token).strip()
    headers["Authorization"] = tok if tok.lower().startswith("bearer ") else f"Bearer {tok}"
    return headers, None


def _gcs_pct_enc(text: str) -> str:
    out = []
    for ch in str(text):
        o = ord(ch)
        if o < 128 and (ch.isalnum() or ch in "-_.~"):
            out.append(ch)
        else:
            for b in ch.encode("utf-8"):
                out.append(f"%{b:02X}")
    return "".join(out)


def _gcs_object_url(api: str, bucket: str, object_name: str) -> str:
    return f"{api}/b/{_gcs_pct_enc(bucket)}/o/{_gcs_pct_enc(str(object_name))}"


def _gcs_norm_prefix(prefix: Optional[str]) -> str:
    if not prefix:
        return ""
    p = str(prefix).replace("\\", "/").lstrip("/")
    return p if not p or p.endswith("/") else p + "/"


def _gcs_list_objects(api, bucket, headers, limit, timeout, verify_ssl, prefix=None, delimiter=None):
    records = []
    cap = min(max(int(limit or 25), 1), 1000)
    page_token = None
    status = 0
    url = f"{api}/b/{_gcs_pct_enc(bucket)}/o"
    while len(records) < cap:
        params = {"maxResults": min(cap - len(records), 1000)}
        if prefix:
            params["prefix"] = prefix
        if delimiter:
            params["delimiter"] = delimiter
        if page_token:
            params["pageToken"] = page_token
        resp = requests.get(url, headers=headers, params=params, timeout=timeout, verify=verify_ssl)
        status = resp.status_code
        if status >= 400:
            return records, status, resp.text[:1000], []
        data = resp.json() if resp.text else {}
        items = data.get("items") if isinstance(data, dict) else None
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    records.append(item)
                    if len(records) >= cap:
                        return records[:cap], status, "ok", data.get("prefixes") or []
        prefixes = data.get("prefixes") if isinstance(data, dict) else []
        page_token = data.get("nextPageToken") if isinstance(data, dict) else None
        if not page_token:
            return records[:cap], status, "ok", prefixes if isinstance(prefixes, list) else []
    return records[:cap], status, "ok", []
