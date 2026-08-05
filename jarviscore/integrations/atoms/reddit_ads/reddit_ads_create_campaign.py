import requests
from typing import Any, Dict, List, Optional

def reddit_ads_create_campaign(auth_info: dict, payload: Dict[str, Any], timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Create a campaign. Official: https://ads-api.reddit.com/docs/v3/"""
    try:
        if not isinstance(payload, dict) or not payload:
            return _ra_provision({}, 400, "payload is required")
        url, err = _ra_account_path(base_url, auth_info, "/campaigns")
        if err:
            return _ra_provision({}, 400, err)
        resp, body, status, msg = _ra_request("post", url, auth_info, json_body=_ra_body(payload), timeout=timeout, verify_ssl=verify_ssl)
        if status >= 400:
            return _ra_provision(body if isinstance(body, dict) else {}, status, msg)
        return _ra_provision(body if isinstance(body, dict) else {}, status, "ok")
    except Exception as e:
        return _ra_provision({}, 500, str(e))


# Reddit Ads API v3 — Official docs: https://ads-api.reddit.com/docs/v3/


def _ra_root(base_url):
    root = (base_url or "https://ads-api.reddit.com/api/v3").strip().rstrip("/")
    if not root.endswith("/api/v3"):
        if "/api/v3" in root:
            root = root.split("/api/v3")[0] + "/api/v3"
        else:
            root = root + "/api/v3"
    return root, None


def _ra_account(auth_info):
    auth_info = auth_info or {}
    account_id = auth_info.get("account_id") or auth_info.get("ad_account_id") or auth_info.get("accountId")
    if not account_id:
        return None, "auth_info.account_id is required"
    return str(account_id).strip(), None


def _ra_auth(auth_info, json_body=False):
    auth_info = auth_info or {}
    token = auth_info.get("access_token")
    if not token:
        return None, "auth_info.access_token is required"
    ua = auth_info.get("user_agent") or auth_info.get("app_name") or "jarviscoreIntegration/1.0"
    t = str(token).strip()
    headers = {"Accept": "application/json", "Authorization": t if t.lower().startswith("bearer ") else f"Bearer {t}", "User-Agent": str(ua).strip()}
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers, None


def _ra_cap(limit):
    return min(max(int(limit or 25), 1), 100)


def _ra_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _ra_provision(data, status, msg, fallback_id=None):
    obj = _ra_entity(data) or (data if isinstance(data, dict) else {})
    pid = (obj.get("id") if isinstance(obj, dict) else None) or fallback_id
    ids = [pid] if pid not in (None, "") else []
    rec = obj if obj else ({"id": pid} if ids else {})
    return {"records": [rec] if rec else [], "data_count": 1 if rec else 0, "status": status, "message": msg, "provision_ids": ids}


def _ra_err(resp, body=None):
    if isinstance(body, dict):
        err = body.get("error") or body.get("message")
        if isinstance(err, dict):
            return str(err.get("message") or err)[:1000]
        if err:
            return str(err)[:1000]
    return (resp.text if resp is not None else "request failed")[:1000]


def _ra_rows(body):
    if not isinstance(body, dict):
        return []
    data = body.get("data")
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def _ra_entity(body):
    rows = _ra_rows(body)
    if rows:
        return rows[0]
    if isinstance(body, dict) and isinstance(body.get("data"), dict):
        return body["data"]
    return None


def _ra_body(payload):
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        return payload
    return {"data": payload if isinstance(payload, dict) else {}}


def _ra_request(method, url, auth_info, params=None, json_body=None, timeout=30, verify_ssl=True):
    headers, err = _ra_auth(auth_info, json_body=(json_body is not None))
    if err:
        return None, None, 401, err
    kwargs = {"headers": headers, "timeout": timeout, "verify": verify_ssl}
    if method == "get":
        resp = requests.get(url, params=params, **kwargs)
    elif method == "post":
        resp = requests.post(url, params=params, json=json_body, **kwargs)
    elif method == "patch":
        resp = requests.patch(url, params=params, json=json_body, **kwargs)
    else:
        return None, None, 400, f"unsupported method {method}"
    try:
        body = resp.json() if resp.content else {}
    except Exception:
        body = {}
    if resp.status_code >= 400:
        return resp, body, resp.status_code, _ra_err(resp, body)
    return resp, body, resp.status_code, "ok"


def _ra_account_path(base_url, auth_info, suffix):
    root, err = _ra_root(base_url)
    if err:
        return None, err
    account_id, err = _ra_account(auth_info)
    if err:
        return None, err
    suffix = suffix if suffix.startswith("/") else "/" + suffix
    return root + "/ad_accounts/" + account_id + suffix, None


def _ra_list(base_url, auth_info, suffix, limit, timeout, verify_ssl, params=None):
    cap = _ra_cap(limit)
    url, err = _ra_account_path(base_url, auth_info, suffix)
    if err:
        return [], 400, err
    records = []
    next_url = None
    status = 200
    msg = "ok"
    while len(records) < cap:
        if next_url:
            resp, body, status, msg = _ra_request("get", next_url, auth_info, timeout=timeout, verify_ssl=verify_ssl)
        else:
            req_params = dict(params or {})
            req_params.setdefault("page.size", min(100, cap))
            resp, body, status, msg = _ra_request("get", url, auth_info, params=req_params, timeout=timeout, verify_ssl=verify_ssl)
        if status >= 400:
            return records, status, msg
        batch = _ra_rows(body)
        if not batch:
            break
        records.extend(batch)
        pag = body.get("pagination") if isinstance(body, dict) else {}
        next_url = pag.get("next_url") if isinstance(pag, dict) else None
        if not next_url or len(batch) < 1:
            break
    return records[:cap], status, msg


def _ra_match(record, query):
    q = str(query).lower()
    for key in ("id", "name", "campaign_id", "ad_group_id", "configured_status", "objective"):
        val = record.get(key)
        if val is not None and q in str(val).lower():
            return True
    return False
