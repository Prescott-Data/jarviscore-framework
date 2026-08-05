import requests
from typing import Any, Dict, List, Optional


def plausible_list_reports(auth_info: dict, limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Aggregate site metrics report via Stats v2 query. Official: https://plausible.io/docs/stats-api"""
    try:
        auth_info = auth_info or {}
        extra = {
            "metrics": auth_info.get("metrics") or ["visitors", "pageviews", "visits", "bounce_rate", "visit_duration"],
        }
        body, err = _pl_query(auth_info, extra=extra)
        if err:
            return _pl_dataset([], 400, err)
        resp, data, status, msg = _pl_stats_query(base_url, auth_info, body, timeout, verify_ssl)
        if status >= 400:
            return _pl_dataset([], status, msg)
        records = _pl_rows(data)[: _pl_cap(limit)]
        return _pl_dataset(records, status, msg)
    except Exception as e:
        return _pl_dataset([], 500, str(e))


# Plausible Analytics API — Events: https://plausible.io/docs/events-api | Stats v2: https://plausible.io/docs/stats-api


def _pl_host(base_url, auth_info):
    auth_info = auth_info or {}
    host = (base_url or auth_info.get("plausible_url") or auth_info.get("base_url") or "https://plausible.io").strip().rstrip("/")
    if host.endswith("/api"):
        host = host[:-4]
    return host.rstrip("/") or "https://plausible.io"


def _pl_site(auth_info, payload=None):
    auth_info = auth_info or {}
    site = auth_info.get("site_id") or auth_info.get("domain")
    if isinstance(payload, dict):
        site = payload.get("domain") or payload.get("site_id") or site
    return site


def _pl_stats_token(auth_info):
    auth_info = auth_info or {}
    return (
        auth_info.get("stats_api_key")
        or auth_info.get("api_key")
    )


def _pl_stats_auth(auth_info):
    token = _pl_stats_token(auth_info)
    if not token:
        return None, "auth_info.stats_api_key or api_key is required for Stats API"
    t = str(token).strip()
    headers = {
        "Authorization": t if t.lower().startswith("bearer ") else f"Bearer {t}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    return headers, None


def _pl_cap(limit):
    return min(max(int(limit or 25), 1), 10000)


def _pl_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _pl_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get("id") or obj.get("name") or fallback_id
    ids = [pid] if pid not in (None, "") else []
    rec = obj if obj else ({"id": pid, "name": pid} if ids else {})
    return {"records": [rec] if rec else [], "data_count": 1 if rec else 0, "status": status, "message": msg, "provision_ids": ids}


def _pl_err(resp, body=None):
    if isinstance(body, dict):
        err = body.get("error") or body.get("message")
        if err:
            return str(err)[:1000]
    return (resp.text if resp is not None else "request failed")[:1000]


def _pl_query(auth_info, extra=None, payload=None):
    auth_info = auth_info or {}
    site = _pl_site(auth_info, payload)
    if not site:
        return None, "auth_info.site_id or domain is required"
    body = {
        "site_id": site,
        "metrics": auth_info.get("metrics") or ["visitors", "pageviews"],
        "date_range": auth_info.get("date_range") or "30d",
    }
    dims = auth_info.get("dimensions")
    if dims:
        body["dimensions"] = dims
    filters = auth_info.get("filters")
    if filters:
        body["filters"] = filters
    order_by = auth_info.get("order_by")
    if order_by:
        body["order_by"] = order_by
    pagination = auth_info.get("pagination")
    if pagination:
        body["pagination"] = pagination
    if isinstance(extra, dict):
        body.update(extra)
    if isinstance(payload, dict):
        for key in ("site_id", "metrics", "date_range", "dimensions", "filters", "order_by", "pagination", "include"):
            if key in payload and payload[key] is not None:
                body[key] = payload[key]
    return body, None


def _pl_rows(data, metric_names=None):
    rows = []
    if not isinstance(data, dict):
        return rows
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    q = meta.get("query") if isinstance(meta.get("query"), dict) else {}
    dims = q.get("dimensions") if isinstance(q.get("dimensions"), list) else None
    metrics = metric_names or q.get("metrics") if isinstance(q.get("metrics"), list) else None
    for item in data.get("results") or []:
        if not isinstance(item, dict):
            continue
        row = {}
        dvals = item.get("dimensions") or []
        if isinstance(dvals, list):
            for i, val in enumerate(dvals):
                key = dims[i] if isinstance(dims, list) and i < len(dims) else f"dimension_{i}"
                row[key] = val
        mvals = item.get("metrics") or []
        if isinstance(mvals, list):
            for i, val in enumerate(mvals):
                key = metrics[i] if isinstance(metrics, list) and i < len(metrics) else f"metric_{i}"
                row[key] = val
        rows.append(row)
    return rows


def _pl_stats_query(base_url, auth_info, query_body, timeout=30, verify_ssl=True):
    host = _pl_host(base_url, auth_info)
    headers, err = _pl_stats_auth(auth_info)
    if err:
        return None, None, 401, err
    resp = requests.post(host + "/api/v2/query", headers=headers, json=query_body, timeout=timeout, verify=verify_ssl)
    try:
        body = resp.json() if resp.content else {}
    except Exception:
        body = {}
    if resp.status_code >= 400:
        return resp, body, resp.status_code, _pl_err(resp, body)
    return resp, body, resp.status_code, "ok"
