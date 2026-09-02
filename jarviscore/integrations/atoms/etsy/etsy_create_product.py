import requests
from typing import Any, Dict, List, Optional

# Etsy Open API v3 — https://developers.etsy.com/documentation/essentials/requests
_ETSY_API_SUFFIX = "/v3/application"


def etsy_create_product(auth_info: dict, shop_id: str, payload: Dict[str, Any], timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Create draft listing (POST /v3/application/shops/{shop_id}/listings, form body). Requires x-api-key (keystring:shared_secret) and OAuth Bearer token per Etsy Open API v3. Official: https://developers.etsy.com/documentation/reference#operation/createDraftListing"""
    try:
        if not payload or not isinstance(payload, dict):
            return {"records": [], "data_count": 0, "status": 400, "message": "payload is required"}
        api, err = _etsy_api_root(base_url)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err}
        sid, err = _etsy_shop_id(shop_id, auth_info)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err}
        headers, auth_err = _etsy_auth(auth_info, form=True)
        if auth_err:
            return {"records": [], "data_count": 0, "status": 401, "message": auth_err}
        resp = requests.post(
            f"{api}/shops/{sid}/listings",
            headers=headers,
            data=_etsy_form_body(payload),
            timeout=timeout,
            verify=verify_ssl,
        )
        if resp.status_code >= 400:
            return {"records": [], "data_count": 0, "status": resp.status_code, "message": resp.text[:1000]}
        data = resp.json() if resp.text else {}
        records = _etsy_results(data)
        return {
            "records": records,
            "data_count": len(records),
            "status": resp.status_code,
            "message": "ok",
            "provision_ids": _etsy_provision_id(data, ("listing_id",)),
        }
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}



def _etsy_api_root(base_url: str):
    root = (base_url or "").rstrip("/")
    if not root:
        return None, "base_url is required (https://openapi.etsy.com/v3/application)"
    if not root.endswith("/v3/application"):
        if root.endswith("/v3"):
            root = f"{root}/application"
        elif _host_is(root, "etsy.com") and _ETSY_API_SUFFIX not in root:
            return None, "base_url must be the Etsy Open API v3 root (https://openapi.etsy.com/v3/application)"
    return root, None


def _etsy_pct_enc(text: str) -> str:
    out = []
    for ch in str(text):
        o = ord(ch)
        if o < 128 and (ch.isalnum() or ch in "-_.~"):
            out.append(ch)
        elif ch == " ":
            out.append("+")
        else:
            for b in ch.encode("utf-8"):
                out.append(f"%{b:02X}")
    return "".join(out)


def _etsy_api_key(auth_info):
    auth_info = auth_info or {}
    return auth_info.get("api_key")


def _etsy_auth(auth_info, form=False, require_oauth=True):
    auth_info = auth_info or {}
    headers = {"Accept": "application/json"}
    if form:
        headers["Content-Type"] = "application/x-www-form-urlencoded; charset=utf-8"
    api_key = _etsy_api_key(auth_info)
    if not api_key:
        return None, "auth_info.api_key is required"
    headers["x-api-key"] = str(api_key)
    token = auth_info.get("access_token")
    if token:
        tok = str(token).strip()
        headers["Authorization"] = tok if tok.lower().startswith("bearer ") else f"Bearer {tok}"
    elif require_oauth:
        return None, "auth_info.access_token is required for this endpoint"
    return headers, None


def _etsy_shop_id(shop_id, auth_info):
    sid = shop_id or (auth_info or {}).get("shop_id")
    if sid in (None, ""):
        return None, "shop_id is required (or auth_info.shop_id)"
    return str(sid).strip(), None


def _etsy_results(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        results = data.get("results")
        if isinstance(results, list):
            return results
        for key in ("listing_id", "receipt_id", "user_id"):
            if data.get(key) is not None:
                return [data]
    return []


def _etsy_form_value(val):
    if val is None:
        return None
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, list):
        parts = []
        for item in val:
            sv = _etsy_form_value(item)
            if sv is not None:
                parts.append(sv)
        return ",".join(parts)
    return str(val)


def _etsy_form_body(fields):
    pairs = []
    for key, val in (fields or {}).items():
        if val is None:
            continue
        pairs.append(f"{_etsy_pct_enc(str(key))}={_etsy_pct_enc(_etsy_form_value(val))}")
    return "&".join(pairs)


def _etsy_paginate(url, headers, base_params, limit, timeout, verify_ssl):
    records = []
    cap = min(max(int(limit or 25), 1), 100)
    offset = 0
    status = 0
    while len(records) < cap:
        page_limit = min(cap - len(records), 100)
        params = dict(base_params or {})
        params["limit"] = page_limit
        params["offset"] = offset
        resp = requests.get(url, headers=headers, params=params, timeout=timeout, verify=verify_ssl)
        status = resp.status_code
        if status >= 400:
            return records, status, resp.text[:1000]
        data = resp.json() if resp.text else {}
        batch = _etsy_results(data)
        for item in batch:
            if isinstance(item, dict):
                records.append(item)
                if len(records) >= cap:
                    return records[:cap], status, "ok"
        if len(batch) < page_limit:
            break
        offset += page_limit
        if offset > 100000:
            break
    return records[:cap], status, "ok"


def _etsy_provision_id(data, keys):
    if not isinstance(data, dict):
        return []
    for key in keys:
        val = data.get(key)
        if val not in (None, ""):
            return [str(val)]
    return []


def _etsy_not_supported(msg):
    return {"records": [], "data_count": 0, "status": 501, "message": msg}


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
