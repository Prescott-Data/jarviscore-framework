import requests
from typing import Any, Dict, List, Optional

# Kissmetrics REST API v3 — https://support.kissmetrics.io/reference/v3queriesreport
KM_API = "https://query.kissmetrics.io/v3"


def kissmetrics_run_report(auth_info: dict, report_id: str, payload: Dict[str, Any], timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Run report in kissmetrics. Official: https://www.kissmetrics.io/product/workflows/api"""
    try:
        if not report_id:
            return {"records": [], "data_count": 0, "status": 400, "message": "report_id is required"}
        api, err = _km_api_root(base_url)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err}
        headers, basic, auth_err = _km_auth(auth_info)
        if auth_err:
            return {"records": [], "data_count": 0, "status": 401, "message": auth_err}
        body = dict(payload or {})
        body.setdefault("report_id", report_id)
        body.setdefault("date_range", {"type": "preset", "preset": "this_month_to_date"})
        resp = _km_post(f"{api}/queries/report", headers, basic, body, timeout, verify_ssl)
        if resp.status_code >= 400:
            return {"records": [], "data_count": 0, "status": resp.status_code, "message": resp.text[:1000]}
        records = _km_records(resp.json() if resp.text else {})
        return {"records": records, "data_count": len(records), "status": resp.status_code, "message": "ok"}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}



def _km_api_root(base_url):
    root = (base_url or KM_API).rstrip("/")
    if "kissmetrics.io" not in root:
        return None, "base_url must be https://query.kissmetrics.io/v3"
    if not root.endswith("/v3"):
        if root.endswith("/v3.0"):
            root = root[:-2]
        elif "/v3" not in root:
            root = f"{root}/v3"
    return root, None


def _km_auth(auth_info):
    auth_info = auth_info or {}
    api_key = auth_info.get("api_key")
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if not api_key:
        return headers, None, "auth_info requires api_key"
    return headers, (str(api_key).strip(), ""), None


def _km_post(url, headers, basic, body, timeout, verify_ssl):
    return requests.post(url, headers=headers, auth=basic, json=body, timeout=timeout, verify=verify_ssl)


def _km_records(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("data", "results", "rows", "report"):
            batch = data.get(key)
            if isinstance(batch, list):
                return batch
        return [data]
    return []
