import requests
from typing import Any, Dict, List, Optional

# Less Annoying CRM API v2 — https://account.lessannoyingcrm.com/api_docs/v2/Getting_Started/Tutorials
LACRM_API = "https://api.lessannoyingcrm.com/v2"

def less_annoying_crm_update_contact(auth_info: dict, contact_id: str, payload: Dict[str, Any], timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Update contact via EditContact. Official: https://account.lessannoyingcrm.com/api_docs/v2/Core_Functions/Contacts"""
    try:
        if not contact_id: return {"records": [], "data_count": 0, "status": 400, "message": "contact_id is required"}
        base, err = _lacrm_root(base_url)
        if err: return {"records": [], "data_count": 0, "status": 400, "message": err}
        headers, aerr = _lacrm_auth(auth_info)
        if aerr: return {"records": [], "data_count": 0, "status": 401, "message": aerr}
        params = dict(payload or {})
        params["ContactId"] = str(contact_id)
        resp = _lacrm_call(base, headers, "EditContact", params, timeout, verify_ssl)
        data = _lacrm_data(resp)
        errm = _lacrm_err(resp, data)
        if errm: return {"records": [], "data_count": 0, "status": resp.status_code, "message": errm}
        return {"records": [{"ContactId": contact_id}], "data_count": 1, "status": resp.status_code, "message": "ok", "provision_ids": [contact_id]}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}



def _lacrm_root(base_url):
    root = (base_url or LACRM_API).rstrip("/")
    if not root.endswith("/v2"):
        if _host_is(root, "lessannoyingcrm.com"):
            root = root + "/v2" if not root.endswith("/v2") else root
        else:
            return None, "base_url must be https://api.lessannoyingcrm.com/v2"
    return root + "/", None


def _lacrm_auth(auth_info):
    auth_info = auth_info or {}
    token = auth_info.get("api_key")
    if not token:
        return None, "auth_info.api_key is required"
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    tok = str(token).strip()
    headers["Authorization"] = tok if tok.lower().startswith("bearer ") else tok
    return headers, None


def _lacrm_call(base, headers, function, parameters, timeout, verify_ssl):
    body = {"Function": function, "Parameters": parameters or {}}
    return requests.post(base, headers=headers, json=body, timeout=timeout, verify=verify_ssl)


def _lacrm_data(resp):
    try:
        return resp.json() if resp.text else {}
    except Exception:
        return {}


def _lacrm_err(resp, data):
    if resp.status_code >= 400:
        if isinstance(data, dict):
            msg = data.get("ErrorDescription") or data.get("Error") or data.get("message")
            if msg:
                return str(msg)
        return resp.text[:1000]
    if isinstance(data, dict) and data.get("ErrorDescription"):
        return str(data["ErrorDescription"])
    return None


def _lacrm_results(data):
    if isinstance(data, dict):
        results = data.get("Results")
        if isinstance(results, list):
            return results
    return []


def _lacrm_paginate(base, headers, function, extra, limit, timeout, verify_ssl):
    records = []
    cap = min(max(int(limit or 25), 1), 10000)
    page = 1
    status = 0
    while len(records) < cap:
        params = dict(extra or {})
        params["MaxNumberOfResults"] = min(cap - len(records), 500)
        params["Page"] = page
        resp = _lacrm_call(base, headers, function, params, timeout, verify_ssl)
        data = _lacrm_data(resp)
        status = resp.status_code
        err = _lacrm_err(resp, data)
        if err:
            return records, status, err
        batch = _lacrm_results(data)
        if not batch:
            break
        records.extend([r for r in batch if isinstance(r, dict)])
        if not data.get("HasMoreResults") or len(batch) < params["MaxNumberOfResults"]:
            break
        page += 1
        if page > 100:
            break
    return records[:cap], status, "ok"


def _lacrm_single_contact(data):
    if isinstance(data, dict) and data.get("ContactId"):
        return [data]
    contact = data.get("Contact") if isinstance(data, dict) else None
    if isinstance(contact, dict):
        return [contact]
    return []


def _lacrm_single_pipeline(data):
    if isinstance(data, dict) and data.get("PipelineItemId"):
        return [data]
    item = data.get("PipelineItem") if isinstance(data, dict) else None
    if isinstance(item, dict):
        return [item]
    return []


def _lacrm_provision_contact(data):
    if isinstance(data, dict) and data.get("ContactId"):
        return [data["ContactId"]]
    return []


def _lacrm_provision_pipeline(data):
    if isinstance(data, dict) and data.get("PipelineItemId"):
        return [data["PipelineItemId"]]
    return []


def _lacrm_pipeline_ids(base, headers, timeout, verify_ssl):
    resp = _lacrm_call(base, headers, "GetPipelines", {}, timeout, verify_ssl)
    data = _lacrm_data(resp)
    err = _lacrm_err(resp, data)
    if err:
        return [], resp.status_code, err
    pipelines = data.get("Pipelines") if isinstance(data, dict) else None
    ids = []
    if isinstance(pipelines, list):
        for p in pipelines:
            if isinstance(p, dict) and p.get("PipelineId"):
                ids.append(p["PipelineId"])
    return ids, resp.status_code, None


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
