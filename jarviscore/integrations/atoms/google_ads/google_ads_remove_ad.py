import requests
from typing import Any, Dict, List, Optional

# Google Ads API — https://developers.google.com/google-ads/api/rest/overview
# Ads are ad_group_ad resources (resource name customers/{cid}/adGroupAds/{adGroupId}~{adId}).
_GADS_API_ROOT = "https://googleads.googleapis.com/v24"


def google_ads_remove_ad(auth_info: dict, customer_id: str, ad_id: str, resource_name: Optional[str] = None, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Remove a ad in google ads. Official: https://developers.google.com/google-ads/api/rest/reference/rest/v24/customers.adGroupAds/mutate"""
    try:
        api, err = _gads_api_root(base_url)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err, "provision_ids": []}
        cid, err = _gads_customer_id(customer_id, auth_info)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err, "provision_ids": []}
        headers, auth_err = _gads_auth(auth_info, json_body=True)
        if auth_err:
            return {"records": [], "data_count": 0, "status": 401, "message": auth_err}
        rn = resource_name
        if not rn and ad_id:
            rn, status, msg = _gads_resolve_ad(api, cid, headers, ad_id, timeout, verify_ssl)
            if not rn:
                return {"records": [], "data_count": 0, "status": status or 404, "message": msg or "ad not found", "provision_ids": []}
        if not rn:
            return {"records": [], "data_count": 0, "status": 400, "message": "resource_name or ad_id is required", "provision_ids": []}
        body = {"operations": [{"remove": rn}]}
        data, status, msg = _gads_mutate(api, cid, "adGroupAds", headers, body, timeout, verify_ssl)
        if status >= 400 or msg != "ok":
            return {"records": [], "data_count": 0, "status": status, "message": msg, "provision_ids": []}
        return _gads_provision_response(data, status)
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e), "provision_ids": []}



def _gads_api_root(base_url: str):
    root = (base_url or _GADS_API_ROOT).rstrip("/")
    if "googleads.googleapis.com" not in root:
        return None, "base_url must be Google Ads API root (https://googleads.googleapis.com/v24)"
    return root, None


def _gads_customer_id(customer_id: Optional[str], auth_info: Optional[Dict[str, Any]]):
    auth_info = auth_info or {}
    cid = customer_id or auth_info.get("customer_id") or auth_info.get("customerId")
    if cid in (None, ""):
        return None, "customer_id is required (or auth_info.customer_id)"
    return str(cid).replace("-", ""), None


def _gads_auth(auth_info: Optional[Dict[str, Any]], json_body: bool = False) -> tuple:
    auth_info = auth_info or {}
    headers = {"Accept": "application/json"}
    if json_body:
        headers["Content-Type"] = "application/json"
    token = auth_info.get("access_token")
    if not token:
        return None, "auth_info requires access_token"
    tok = str(token).strip()
    headers["Authorization"] = tok if tok.lower().startswith("bearer ") else f"Bearer {tok}"
    dev = auth_info.get("developer_token") or auth_info.get("developerToken")
    if dev:
        headers["developer-token"] = str(dev)
    login = auth_info.get("login_customer_id") or auth_info.get("loginCustomerId")
    if login not in (None, ""):
        headers["login-customer-id"] = str(login).replace("-", "")
    return headers, None


def _gads_search(
    api: str,
    customer_id: str,
    headers: Dict[str, str],
    query: str,
    limit: int,
    timeout: int,
    verify_ssl: bool,
) -> tuple:
    records: List[Dict[str, Any]] = []
    cap = min(max(int(limit or 25), 1), 10000)
    page_token = None
    status = 0
    url = f"{api}/customers/{customer_id}/googleAds:search"
    while len(records) < cap:
        body: Dict[str, Any] = {"query": query}
        if page_token:
            body["pageToken"] = page_token
        resp = requests.post(url, headers=headers, json=body, timeout=timeout, verify=verify_ssl)
        status = resp.status_code
        if status >= 400:
            return records, status, resp.text[:1000]
        data = resp.json() if resp.text else {}
        rows = data.get("results") if isinstance(data, dict) else None
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    records.append(row)
                    if len(records) >= cap:
                        break
        page_token = data.get("nextPageToken") if isinstance(data, dict) else None
        if not page_token or len(records) >= cap:
            break
    return records, status, "ok"


def _gads_mutate(
    api: str,
    customer_id: str,
    resource: str,
    headers: Dict[str, str],
    body: Dict[str, Any],
    timeout: int,
    verify_ssl: bool,
) -> tuple:
    url = f"{api}/customers/{customer_id}/{resource}:mutate"
    resp = requests.post(url, headers=headers, json=body, timeout=timeout, verify=verify_ssl)
    status = resp.status_code
    data = resp.json() if resp.content else {}
    if status >= 400:
        msg = data if isinstance(data, dict) else resp.text[:1000]
        return data, status, str(msg)
    return data, status, "ok"


def _gads_provision_ids(data: Any) -> List[Any]:
    ids: List[Any] = []
    if not isinstance(data, dict):
        return ids
    for row in data.get("results") or []:
        if not isinstance(row, dict):
            continue
        for key in ("resourceName", "resource_name"):
            if row.get(key):
                ids.append(row.get(key))
                break
    return ids


def _gads_provision_response(data: Any, status: int) -> Dict[str, Any]:
    records = [data] if isinstance(data, dict) else []
    provision_ids = _gads_provision_ids(data)
    return {
        "records": records,
        "data_count": len(records),
        "status": status,
        "message": "ok",
        "provision_ids": provision_ids,
    }


def _gads_resolve_ad(api, cid, headers, ad_id, timeout, verify_ssl):
    query = (
        "SELECT ad_group_ad.resource_name FROM ad_group_ad "
        f"WHERE ad_group_ad.ad.id = {ad_id} LIMIT 1"
    )
    rows, status, msg = _gads_search(api, cid, headers, query, 1, timeout, verify_ssl)
    if status >= 400 or not rows:
        return None, status, msg
    aga = rows[0].get("adGroupAd") or rows[0].get("ad_group_ad") or {}
    return (aga.get("resourceName") or aga.get("resource_name")), status, "ok"
