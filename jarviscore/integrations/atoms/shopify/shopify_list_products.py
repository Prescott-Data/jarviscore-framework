import requests
from typing import Any, Dict, List, Optional

def shopify_list_products(auth_info: dict, shop: str = "", limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Shopify Admin REST: list products. Official: https://shopify.dev/docs/api/admin-rest/latest/resources/product#get-products"""
    try:
        root, err = _sh_root(base_url, shop, auth_info)
        if err:
            return _sh_dataset([], 400, err)
        records, status, msg = _sh_paginate(root, "/products.json", auth_info, "products", limit, timeout, verify_ssl)
        return _sh_dataset(records, status, msg)
    except Exception as e:
        return _sh_dataset([], 500, str(e))


# Shopify Admin REST API — Official docs: https://shopify.dev/docs/api/admin-rest


def _sh_root(base_url, shop, auth_info):
    auth_info = auth_info or {}
    shop = (shop or auth_info.get("shop") or auth_info.get("shop_domain") or "").strip().rstrip("/")
    if shop and not shop.startswith("http"):
        shop = f"https://{shop}" if ".myshopify.com" in shop else f"https://{shop}.myshopify.com"
    root = (base_url or auth_info.get("shopify_url") or shop or auth_info.get("base_url") or "").strip().rstrip("/")
    if not root:
        return None, "base_url or shop is required (https://{shop}.myshopify.com)"
    if not root.endswith("/admin/api"):
        ver = auth_info.get("api_version") or "2024-04"
        if "/admin/api/" not in root:
            root = root + f"/admin/api/{ver}"
    return root, None


def _sh_auth(auth_info):
    auth_info = auth_info or {}
    token = auth_info.get("api_key")
    if not token:
        return None, "auth_info.access_token is required"
    t = str(token).strip()
    return {"Accept": "application/json", "X-Shopify-Access-Token": t.replace("Bearer ", "")}, None


def _sh_cap(limit):
    return min(max(int(limit or 25), 1), 250)


def _sh_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _sh_provision(data, status, msg, resource, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    inner = obj.get(resource) if isinstance(obj.get(resource), dict) else obj
    pid = (inner or {}).get("id") or fallback_id
    ids = [pid] if pid not in (None, "") else []
    rec = inner if inner else ({"id": pid} if ids else {})
    return {"records": [rec] if rec else [], "data_count": 1 if rec else 0, "status": status, "message": msg, "provision_ids": ids}


def _sh_err(resp):
    try:
        data = resp.json()
        if isinstance(data, dict):
            errs = data.get("errors")
            if errs:
                return str(errs)[:1000]
    except Exception:
        pass
    return (resp.text or f"HTTP {resp.status_code}")[:1000]


def _sh_rows(data, resource):
    if isinstance(data, dict):
        items = data.get(resource)
        if isinstance(items, list):
            return [x for x in items if isinstance(x, dict)]
        one = data.get(resource.rstrip('s'))
        if isinstance(one, dict):
            return [one]
    return []


def _sh_paginate(root, path, auth_info, resource, limit, timeout, verify_ssl):
    headers, err = _sh_auth(auth_info)
    if err:
        return [], 401, err
    cap = _sh_cap(limit)
    records = []
    url = root + path
    params = {"limit": min(cap, 250)}
    pages = 0
    while len(records) < cap and pages < 50:
        pages += 1
        resp = requests.get(url, headers=headers, params=params, timeout=timeout, verify=verify_ssl)
        if resp.status_code >= 400:
            return records, resp.status_code, _sh_err(resp)
        try:
            data = resp.json()
        except Exception:
            data = {}
        batch = _sh_rows(data, resource)
        records.extend(batch)
        link = resp.headers.get("Link") or ""
        nxt = None
        if 'rel="next"' in link:
            for part in link.split(","):
                if 'rel="next"' in part:
                    nxt = part.split(";")[0].strip().strip("<> ")
                    break
        if not nxt or not batch:
            break
        url = nxt
        params = None
    return records[:cap], 200, "ok"
