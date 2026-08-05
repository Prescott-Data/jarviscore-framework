import requests
from typing import Any, Dict, List, Optional, Tuple, Union

# LiquidPlanner Classic API — Official docs:
# Getting started https://developer.liquidplanner.com/docs/getting-started
# Auth https://developer.liquidplanner.com/docs/authentication-and-authorization
# Requests https://developer.liquidplanner.com/docs/requests-and-responses
# Filtering https://developer.liquidplanner.com/docs/filtering-requests
# Treeitems https://developer.liquidplanner.com/docs/treeitem-data-model
LP_CLASSIC_API = "https://app.liquidplanner.com/api/v1"


def liquidplanner_get_project(auth_info: dict, workspace_id: str, project_id: str, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Get a project by ID. Official: https://developer.liquidplanner.com/docs/requests-and-responses"""
    try:
        if not project_id:
            return {"records": [], "data_count": 0, "status": 400, "message": "project_id is required"}
        base, err = _lp_root(base_url)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err}
        ws, werr = _lp_workspace(workspace_id, auth_info)
        if werr:
            return {"records": [], "data_count": 0, "status": 400, "message": werr}
        headers, aerr = _lp_headers(auth_info)
        if aerr:
            return {"records": [], "data_count": 0, "status": 401, "message": aerr}
        resp = requests.get(f"{base}/workspaces/{ws}/projects/{project_id}", headers=headers, timeout=timeout, verify=verify_ssl)
        try:
            data = resp.json() if resp.text else {}
        except Exception:
            data = {}
        if resp.status_code >= 400:
            return {"records": [], "data_count": 0, "status": resp.status_code, "message": _lp_error_message(data, resp.text)}
        records = _lp_records(data)
        return {"records": records, "data_count": len(records), "status": resp.status_code, "message": "ok"}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}



def _lp_root(base_url):
    root = (base_url or LP_CLASSIC_API).rstrip("/")
    if "liquidplanner.com" not in root:
        return None, "base_url must be https://app.liquidplanner.com/api/v1"
    return root, None


def _lp_workspace(workspace_id, auth_info):
    auth_info = auth_info or {}
    ws = workspace_id or auth_info.get("workspace_id")
    if ws in (None, ""):
        return None, "workspace_id is required"
    return str(ws), None


def _lp_auth_header(auth_info):
    auth_info = auth_info or {}
    raw = auth_info.get("access_token")
    if not raw:
        return None, "auth_info.access_token is required"
    tok = str(raw).strip()
    prefix = "Bearer "
    return tok if tok.lower().startswith(prefix.lower()) else prefix + tok, None


def _lp_headers(auth_info, json_body=False):
    auth, err = _lp_auth_header(auth_info)
    if err:
        return None, err
    headers = {"Accept": "application/json", "Authorization": auth}
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers, None


def _lp_records(data):
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        if data.get("type") == "Error":
            return []
        if data.get("id") is not None:
            return [data]
    return []


def _lp_error_message(data, fallback=""):
    if isinstance(data, dict) and data.get("type") == "Error":
        return str(data.get("message") or data.get("error") or fallback)[:1000]
    return (fallback or "")[:1000]


def _lp_filter_quote(value):
    text = str(value or "")
    text = text.replace("\\", "\\\\").replace('"', '\\"')
    return '"' + text + '"'


def _lp_write_body(resource, payload):
    if isinstance(payload, dict) and resource in payload:
        return payload
    return {resource: payload if isinstance(payload, dict) else {}}


def _lp_provision(data, status, message="ok"):
    obj = data if isinstance(data, dict) else {}
    obj_id = obj.get("id")
    records = [obj] if obj_id is not None else []
    ids = [obj_id] if obj_id is not None else []
    return {
        "records": records,
        "data_count": len(records),
        "status": status,
        "message": message,
        "provision_ids": ids,
    }


def _lp_cap(records, limit):
    cap = min(max(int(limit or 25), 1), 500)
    return records[:cap]
