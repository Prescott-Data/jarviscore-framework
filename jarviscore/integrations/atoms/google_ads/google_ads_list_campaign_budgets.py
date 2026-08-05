import requests
from typing import Any, Dict, List, Optional

# Google Ads API — https://developers.google.com/google-ads/api/rest/overview
_GADS_API_ROOT = "https://googleads.googleapis.com/v24"


def google_ads_list_campaign_budgets(auth_info: dict, customer_id: str, limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """List a campaign budget in google ads. Official: https://developers.google.com/google-ads/api/docs/rest/common/search"""
    try:
        api, err = _gads_api_root(base_url)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err}
        cid, err = _gads_customer_id(customer_id, auth_info)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err}
        headers, auth_err = _gads_auth(auth_info, json_body=True)
        if auth_err:
            return {"records": [], "data_count": 0, "status": 401, "message": auth_err}
        cap = min(max(int(limit or 25), 1), 10000)
        query = (
            "SELECT campaign_budget.id, campaign_budget.name, campaign_budget.amount_micros, "
            "campaign_budget.delivery_method, campaign_budget.status, campaign_budget.resource_name "
            f"FROM campaign_budget ORDER BY campaign_budget.id LIMIT {cap}"
        )
        records, status, msg = _gads_search(api, cid, headers, query, cap, timeout, verify_ssl)
        if status >= 400 or msg != "ok":
            return {"records": records, "data_count": len(records), "status": status, "message": msg}
        return {"records": records, "data_count": len(records), "status": status, "message": "ok"}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}



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
