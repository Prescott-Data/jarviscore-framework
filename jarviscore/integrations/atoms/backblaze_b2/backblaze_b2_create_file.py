import requests
import hashlib
from typing import Any, Dict, List, Optional


def backblaze_b2_create_file(auth_info: dict, file_name: str, bucket_id: Optional[str] = None, bucket_name: Optional[str] = None, content: str = "", content_type: str = "b2/x-auto", timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Upload a file via b2_get_upload_url and POST to uploadUrl. Official: https://www.backblaze.com/b2/docs/b2_get_upload_url.html"""
    try:
        if not base_url:
            base_url = _B2_DEFAULT_HOST
        if not file_name:
            return {"records": [], "data_count": 0, "status": 400, "message": "file_name is required", "provision_ids": []}
        fail = _b2_auth_fail(auth_info)
        if fail:
            return fail
        raw = content.encode("utf-8") if isinstance(content, str) else b""
        sha1 = hashlib.sha1(raw).hexdigest()
        session, err = _b2_authorize(base_url, auth_info, timeout, verify_ssl)
        if err != "ok":
            return {"records": [], "data_count": 0, "status": 401, "message": err, "provision_ids": []}
        bid, bid_err = _b2_resolve_bucket_id(
            session["api_url"], session["auth_token"], session["account_id"],
            bucket_id, bucket_name, timeout, verify_ssl, session.get("allowed_buckets"),
        )
        if bid_err:
            return {"records": [], "data_count": 0, "status": 400, "message": bid_err, "provision_ids": []}
        up_resp = _b2_post(session["api_url"], "/b2api/v4/b2_get_upload_url", session["auth_token"], {"bucketId": bid}, timeout, verify_ssl)
        if up_resp.status_code >= 400:
            return {"records": [], "data_count": 0, "status": up_resp.status_code, "message": up_resp.text[:1000], "provision_ids": []}
        up = up_resp.json()
        upload_url = up.get("uploadUrl")
        upload_token = up.get("authorizationToken")
        if not upload_url or not upload_token:
            return {"records": [], "data_count": 0, "status": 500, "message": "Missing uploadUrl from b2_get_upload_url", "provision_ids": []}
        headers = {
            "Authorization": upload_token,
            "X-Bz-File-Name": _pct_enc(file_name, safe="/"),
            "Content-Type": content_type,
            "X-Bz-Content-Sha1": sha1,
        }
        put = requests.post(upload_url, headers=headers, data=raw, timeout=timeout, verify=verify_ssl)
        status = put.status_code
        if status >= 400:
            return {"records": [], "data_count": 0, "status": status, "message": put.text[:1000], "provision_ids": []}
        data = put.json() if put.text else {}
        fid = data.get("fileId") if isinstance(data, dict) else None
        records = [data] if isinstance(data, dict) else []
        return {"records": records, "data_count": len(records), "status": status, "message": "ok", "provision_ids": [fid] if fid else []}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e), "provision_ids": []}



def _pct_enc(text, safe=""):
    out = []
    for ch in str(text):
        o = ord(ch)
        if ch in safe or (o < 128 and (ch.isalnum() or ch in "-_.~")):
            out.append(ch)
        else:
            for b in ch.encode("utf-8"):
                out.append(f"%{b:02X}")
    return "".join(out)


def _parse_url(url):
    scheme, rest = ("", url)
    if "://" in url:
        scheme, rest = url.split("://", 1)
    fragment = ""
    if "#" in rest:
        rest, fragment = rest.split("#", 1)
    query = ""
    if "?" in rest:
        rest, query = rest.split("?", 1)
    if "/" in rest:
        netloc, path = rest.split("/", 1)
        path = "/" + path
    else:
        netloc, path = rest, "/"
    return scheme, netloc, path, query, fragment


def _build_url(scheme, netloc, path, query="", fragment=""):
    url = f"{scheme}://{netloc}{path or '/'}"
    if query:
        url += "?" + query
    if fragment:
        url += "#" + fragment
    return url


def _query_pairs(query):
    pairs = []
    for part in (query or "").split("&"):
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
        else:
            k, v = part, ""
        pairs.append((k, v))
    return pairs


def _query_get(url, name):
    _, _, _, query, _ = _parse_url(url)
    for k, v in _query_pairs(query):
        if k == name:
            return v
    return None


def _urlencode(params):
    return "&".join(f"{_pct_enc(str(k))}={_pct_enc(str(v))}" for k, v in params.items())


def _json_escape(value):
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def _json_dumps(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return f'"{_json_escape(value)}"'
    if isinstance(value, dict):
        parts = [f'"{_json_escape(k)}": {_json_dumps(v)}' for k, v in value.items()]
        return "{" + ", ".join(parts) + "}"
    if isinstance(value, list):
        return "[" + ", ".join(_json_dumps(v) for v in value) + "]"
    return f'"{_json_escape(str(value))}"'


def _basename(path):
    p = str(path).replace("\\", "/")
    return p.rsplit("/", 1)[-1] if p else ""


def _guess_mime(path):
    ext = _basename(path).rsplit(".", 1)[-1].lower() if "." in _basename(path) else ""
    return {
        "pdf": "application/pdf",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "txt": "text/plain",
        "csv": "text/csv",
        "json": "application/json",
        "html": "text/html",
        "xml": "application/xml",
        "zip": "application/zip",
    }.get(ext, "application/octet-stream")

# Backblaze B2 Native API — https://www.backblaze.com/b2/docs/b2_get_upload_url.html
_B2_DEFAULT_HOST = "https://api.backblazeb2.com"


def _b2_credentials(auth_info):
    auth_info = auth_info or {}
    key_id = auth_info.get("username")
    app_key = auth_info.get("password")
    if not key_id or not app_key:
        return None, None, "auth_info requires username and password"
    return str(key_id), str(app_key), None


def _b2_authorize_host(base_url):
    host = (base_url or _B2_DEFAULT_HOST).rstrip("/")
    if host.endswith("/b2api/v4"):
        host = host.rsplit("/b2api", 1)[0]
    return host


def _b2_authorize(base_url, auth_info, timeout, verify_ssl):
    host = _b2_authorize_host(base_url)
    key_id, app_key, err = _b2_credentials(auth_info)
    if err:
        return None, err
    resp = requests.get(
        f"{host}/b2api/v4/b2_authorize_account",
        auth=(key_id, app_key),
        headers={"Accept": "application/json"},
        timeout=timeout,
        verify=verify_ssl,
    )
    if resp.status_code >= 400:
        return None, resp.text[:1000]
    data = resp.json()
    if not isinstance(data, dict):
        return None, "Unexpected authorize response"
    api_info = data.get("apiInfo") if isinstance(data.get("apiInfo"), dict) else {}
    storage = api_info.get("storageApi") if isinstance(api_info.get("storageApi"), dict) else {}
    api_url = storage.get("apiUrl") or data.get("apiUrl")
    allowed = storage.get("allowed") if isinstance(storage.get("allowed"), dict) else {}
    allowed_buckets = allowed.get("buckets") if isinstance(allowed.get("buckets"), list) else []
    if not api_url:
        return None, "Missing apiUrl in authorize response"
    return {
        "api_url": str(api_url).rstrip("/"),
        "auth_token": data.get("authorizationToken"),
        "account_id": data.get("accountId"),
        "allowed_buckets": allowed_buckets,
    }, "ok"


def _b2_post(api_url, path, token, body, timeout, verify_ssl):
    return requests.post(
        f"{api_url}{path}",
        headers={"Authorization": token, "Content-Type": "application/json", "Accept": "application/json"},
        json=body,
        timeout=timeout,
        verify=verify_ssl,
    )


def _b2_resolve_bucket_id(api_url, token, account_id, bucket_id, bucket_name, timeout, verify_ssl, allowed_buckets=None):
    if bucket_id:
        return str(bucket_id), None
    if not bucket_name:
        return None, "bucket_id or bucket_name is required"
    for bucket in allowed_buckets or []:
        if isinstance(bucket, dict) and bucket.get("name") == bucket_name and bucket.get("id"):
            return str(bucket.get("id")), None
    resp = _b2_post(api_url, "/b2api/v4/b2_list_buckets", token, {"accountId": account_id}, timeout, verify_ssl)
    if resp.status_code >= 400:
        return None, resp.text[:1000]
    data = resp.json()
    for bucket in data.get("buckets") or []:
        if isinstance(bucket, dict) and bucket.get("bucketName") == bucket_name:
            return str(bucket.get("bucketId")), None
    return None, f"bucket not found: {bucket_name}"


def _b2_auth_fail(auth_info):
    _, _, err = _b2_credentials(auth_info)
    if not err:
        return None
    return {"records": [], "data_count": 0, "status": 401, "message": err, "provision_ids": []}
