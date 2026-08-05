import requests
from typing import Any, Dict, List, Optional

def prestashop_get_product(auth_info: dict, product_id: str, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Get a product by ID. Official: https://devdocs.prestashop-project.org/9/webservice/getting-started/"""
    try:
        if not product_id:
            return _ps_dataset([], 400, "product_id is required")
        root, err = _ps_root(base_url, auth_info)
        if err:
            return _ps_dataset([], 400, err)
        resp, body, status, msg = _ps_request("get", root + "/products/" + str(product_id), auth_info, params={"display": "full"}, timeout=timeout, verify_ssl=verify_ssl)
        if status >= 400:
            return _ps_dataset([], status, msg)
        return _ps_dataset(_ps_rows(body, "products"), status, msg)
    except Exception as e:
        return _ps_dataset([], 500, str(e))


# PrestaShop Webservice API — Official docs: https://devdocs.prestashop-project.org/9/webservice/getting-started/


def _ps_root(base_url, auth_info):
    auth_info = auth_info or {}
    root = (base_url or auth_info.get("prestashop_url") or auth_info.get("shop_url") or auth_info.get("base_url") or "").strip().rstrip("/")
    if not root:
        return None, "base_url is required (https://shop.example.com/api)"
    if root.endswith("/api"):
        pass
    elif "/api/" in root:
        root = root.split("/api/")[0] + "/api"
    else:
        root = root + "/api"
    return root, None


def _ps_auth(auth_info, xml_body=False):
    import base64
    auth_info = auth_info or {}
    key = auth_info.get("api_key")
    if not key:
        return None, "auth_info.api_key is required"
    key = str(key).strip()
    token = base64.b64encode((key + ":").encode("utf-8")).decode("ascii")
    headers = {"Authorization": f"Basic {token}", "Output-Format": "JSON", "Accept": "application/json"}
    if xml_body:
        headers["Content-Type"] = "application/xml"
    return headers, None


def _ps_cap(limit):
    return min(max(int(limit or 25), 1), 500)


def _ps_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _ps_provision(data, status, msg, resource, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    rid = _ps_extract_id(obj, resource) or fallback_id
    ids = [rid] if rid not in (None, "") else []
    rec = _ps_rows(obj, resource)[0] if _ps_rows(obj, resource) else (obj if obj else ({"id": rid} if ids else {}))
    return {"records": [rec] if rec else [], "data_count": 1 if rec else 0, "status": status, "message": msg, "provision_ids": ids}


def _ps_err(resp, body=None):
    if isinstance(body, dict):
        for key in ("errors", "error", "message"):
            val = body.get(key)
            if val:
                return str(val)[:1000]
    return (resp.text if resp is not None else "request failed")[:1000]


def _ps_singular(resource):
    mapping = {"categories": "category", "addresses": "address"}
    if resource in mapping:
        return mapping[resource]
    if resource.endswith("ies"):
        return resource[:-3] + "y"
    if resource.endswith("s"):
        return resource[:-1]
    return resource


def _ps_rows(body, resource):
    if not isinstance(body, dict):
        return []
    singular = _ps_singular(resource)
    block = body.get(resource)
    if block is None and isinstance(body.get("prestashop"), dict):
        block = body["prestashop"].get(resource)
    if block is None and singular in body:
        item = body.get(singular)
        return [item] if isinstance(item, dict) else []
    if isinstance(block, list):
        return [x for x in block if isinstance(x, dict)]
    if isinstance(block, dict):
        inner = block.get(singular)
        if isinstance(inner, list):
            return [x for x in inner if isinstance(x, dict)]
        if isinstance(inner, dict):
            return [inner]
        if block.get("id") is not None:
            return [block]
    return []


def _ps_extract_id(body, resource):
    rows = _ps_rows(body, resource)
    if rows and rows[0].get("id") not in (None, ""):
        return rows[0].get("id")
    singular = _ps_singular(resource)
    obj = body.get(singular) if isinstance(body, dict) else None
    if isinstance(obj, dict) and obj.get("id") not in (None, ""):
        return obj.get("id")
    return None


def _ps_xml_escape(value):
    text = str(value)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _ps_build_xml(resource, payload, resource_id=None):
    singular = _ps_singular(resource)
    payload = payload if isinstance(payload, dict) else {}
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<prestashop xmlns:xlink="http://www.w3.org/1999/xlink">',
        f"  <{singular}>",
    ]
    rid = resource_id if resource_id not in (None, "") else payload.get("id")
    if rid not in (None, ""):
        lines.append(f"    <id><![CDATA[{rid}]]></id>")
    for key, val in payload.items():
        if key == "id" or val is None:
            continue
        if isinstance(val, (dict, list)):
            continue
        lines.append(f"    <{key}><![CDATA[{val}]]></{key}>")
    lines.append(f"  </{singular}>")
    lines.append("</prestashop>")
    return "\n".join(lines)


def _ps_request(method, url, auth_info, params=None, xml_body=None, timeout=30, verify_ssl=True):
    headers, err = _ps_auth(auth_info, xml_body=(xml_body is not None))
    if err:
        return None, None, 401, err
    kwargs = {"headers": headers, "timeout": timeout, "verify": verify_ssl}
    if method == "get":
        resp = requests.get(url, params=params, **kwargs)
    elif method == "post":
        resp = requests.post(url, params=params, data=xml_body, **kwargs)
    elif method == "put":
        resp = requests.put(url, params=params, data=xml_body, **kwargs)
    elif method == "patch":
        resp = requests.patch(url, params=params, data=xml_body, **kwargs)
    else:
        return None, None, 400, f"unsupported method {method}"
    try:
        body = resp.json() if resp.content else {}
    except Exception:
        body = {}
    if resp.status_code >= 400:
        return resp, body, resp.status_code, _ps_err(resp, body)
    return resp, body, resp.status_code, "ok"


def _ps_list(resource, base_url, auth_info, limit, timeout, verify_ssl, extra_params=None):
    root, err = _ps_root(base_url, auth_info)
    if err:
        return [], 400, err
    cap = _ps_cap(limit)
    records = []
    offset = 0
    page_size = min(cap, 100)
    status = 200
    msg = "ok"
    while len(records) < cap:
        params = {"display": "full", "limit": f"{offset},{page_size}"}
        if extra_params:
            params.update(extra_params)
        resp, body, status, msg = _ps_request("get", root + "/" + resource, auth_info, params=params, timeout=timeout, verify_ssl=verify_ssl)
        if status >= 400:
            return records, status, msg
        batch = _ps_rows(body, resource)
        if not batch:
            break
        records.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    return records[:cap], status, msg


def _ps_match(record, query):
    q = str(query).lower()
    for key in ("id", "name", "reference", "email", "firstname", "lastname", "company"):
        val = record.get(key)
        if val is not None and q in str(val).lower():
            return True
    return False
