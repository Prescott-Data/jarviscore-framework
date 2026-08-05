import requests
from typing import Any, Dict, List, Optional

# Google Analytics Data API (GA4) — https://developers.google.com/analytics/devguides/reporting/data/v1
_GA_DATA_ROOT = "https://analyticsdata.googleapis.com/v1beta"
_GA_ADMIN_ROOT = "https://analyticsadmin.googleapis.com/v1beta"


def google_analytics_get_report(auth_info: dict, property_id: str, report_body: Dict[str, Any], timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Get a report by ID from google analytics. Official: https://developers.google.com/analytics/devguides/reporting/data/v1/rest/v1beta/properties/runReport"""
    try:
        api, err = _ga_data_root(base_url)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err}
        pid, err = _ga_property_id(property_id, auth_info)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err}
        if not isinstance(report_body, dict) or not report_body:
            return {"records": [], "data_count": 0, "status": 400, "message": "report_body is required"}
        headers, auth_err = _ga_auth(auth_info, json_body=True)
        if auth_err:
            return {"records": [], "data_count": 0, "status": 401, "message": auth_err}
        url = f"{api}/{pid}:runReport"
        resp = requests.post(url, headers=headers, json=report_body, timeout=timeout, verify=verify_ssl)
        status = resp.status_code
        if status >= 400:
            return {"records": [], "data_count": 0, "status": status, "message": resp.text[:1000]}
        data = resp.json() if resp.text else {}
        records = [data] if isinstance(data, dict) and data else []
        return {"records": records, "data_count": len(records), "status": status, "message": "ok"}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}



def _ga_data_root(base_url: str):
    root = (base_url or _GA_DATA_ROOT).rstrip("/")
    if "analyticsdata.googleapis.com" not in root:
        return None, "base_url must be GA4 Data API root (https://analyticsdata.googleapis.com/v1beta)"
    return root, None


def _ga_admin_root(base_url: str):
    root = (base_url or _GA_ADMIN_ROOT).rstrip("/")
    if "analyticsadmin.googleapis.com" not in root:
        return None, "base_url must be GA4 Admin API root (https://analyticsadmin.googleapis.com/v1beta)"
    return root, None


def _ga_auth(auth_info: Optional[Dict[str, Any]], json_body: bool = False) -> tuple:
    auth_info = auth_info or {}
    headers = {"Accept": "application/json"}
    if json_body:
        headers["Content-Type"] = "application/json"
    token = auth_info.get("access_token")
    if not token:
        return None, "auth_info requires access_token"
    tok = str(token).strip()
    headers["Authorization"] = tok if tok.lower().startswith("bearer ") else f"Bearer {tok}"
    return headers, None


def _ga_property_id(property_id: Optional[str], auth_info: Optional[Dict[str, Any]]):
    auth_info = auth_info or {}
    pid = property_id or auth_info.get("property_id") or auth_info.get("propertyId")
    if pid in (None, ""):
        return None, "property_id is required (or auth_info.property_id)"
    pid = str(pid)
    if not pid.startswith("properties/"):
        pid = f"properties/{pid}"
    return pid, None
