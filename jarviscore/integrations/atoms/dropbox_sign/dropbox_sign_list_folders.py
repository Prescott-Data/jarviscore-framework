import requests
from typing import Any, Dict, List, Optional

# Dropbox Sign API v3 — https://developers.hellosign.com/api/reference/template_list
SIGN_API = "https://api.hellosign.com/v3"


def dropbox_sign_list_folders(auth_info: dict, limit: int = 20, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """List templates (folder catalog alias). Official: https://developers.hellosign.com/api/template/list"""
    try:
        api, err = _sign_api_root(base_url)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err}
        headers, basic, auth_err = _sign_auth(auth_info)
        if auth_err:
            return {"records": [], "data_count": 0, "status": 401, "message": auth_err}
        cap = min(max(int(limit or 20), 1), 100)
        records: List[Dict[str, Any]] = []
        page = 1
        status = 0
        while len(records) < cap:
            page_size = min(cap - len(records), 100)
            params = {"page": page, "page_size": page_size}
            resp = requests.get(
                f"{api}/template/list",
                headers=headers,
                auth=basic,
                params=params,
                timeout=timeout,
                verify=verify_ssl,
            )
            status = resp.status_code
            if status >= 400:
                return {"records": records, "data_count": len(records), "status": status, "message": resp.text[:1000]}
            data = resp.json() if resp.text else {}
            batch = data.get("templates") or []
            if not isinstance(batch, list):
                batch = []
            for item in batch:
                if isinstance(item, dict):
                    records.append(item)
                    if len(records) >= cap:
                        break
            list_info = data.get("list_info") if isinstance(data.get("list_info"), dict) else {}
            if len(records) >= cap or not list_info.get("num_pages") or page >= int(list_info.get("num_pages") or page):
                break
            if len(batch) < page_size:
                break
            page += 1
            if page > 100:
                break
        return {"records": records[:cap], "data_count": len(records[:cap]), "status": status, "message": "ok"}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}



def _sign_api_root(base_url: str):
    root = (base_url or SIGN_API).rstrip("/")
    if root.endswith("/v3"):
        return root, None
    if _host_is(root, "hellosign.com", "dropboxsign.com"):
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


def _host_is(url, *domains):
    """True only if url's hostname equals or is a subdomain of one of domains."""
    from urllib.parse import urlparse
    u = str(url or "").strip()
    if "://" not in u:
        u = "https://" + u
    try:
        host = (urlparse(u).hostname or "").lower()
    except Exception:
        return False
    return any(host == d or host.endswith("." + d) for d in domains)
