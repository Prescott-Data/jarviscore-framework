import requests
from typing import Any, Dict, List, Optional

# Jumia Seller Center API — http://sellerapi.sellercenter.jumia.com/v2.7.11/product-endpoints/productcreate/
JUMIA_SC_API = "http://sellerapi.sellercenter.jumia.com"
SC_VERSION = "1.0"


def jumia_seller_center_create_product(auth_info: dict, payload: Dict[str, Any], timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Create product feed via ProductCreate (XML body). Official: http://sellerapi.sellercenter.jumia.com/v2.7.11/product-endpoints/productcreate/"""
    try:
        if not payload:
            return {"records": [], "data_count": 0, "status": 400, "message": "payload is required"}
        body = _jsc_product_xml(payload)
        if not body:
            return {"records": [], "data_count": 0, "status": 400, "message": "payload must include product fields or xml"}
        base, err = _jsc_root(base_url)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err}
        user_id, api_key, cerr = _jsc_creds(auth_info)
        if cerr:
            return {"records": [], "data_count": 0, "status": 401, "message": cerr, "provision_ids": []}
        resp = _jsc_call(base, "ProductCreate", user_id, api_key, body=body, timeout=timeout, verify_ssl=verify_ssl)
        data = _jsc_json(resp)
        status = 400 if data.get("ErrorResponse") else resp.status_code
        if status >= 400:
            return {"records": [], "data_count": 0, "status": status, "message": _jsc_message(resp, data)}
        feed_ids = _jsc_feed_id(data)
        records = [{"feed_id": fid} for fid in feed_ids] if feed_ids else []
        return {"records": records, "data_count": len(records), "status": status, "message": "ok", "provision_ids": feed_ids}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}



def _jsc_root(base_url):
    root = (base_url or JUMIA_SC_API).rstrip("/")
    if not root:
        return None, "base_url is required (http://sellerapi.sellercenter.jumia.com)"
    return root, None


def _jsc_creds(auth_info):
    auth_info = auth_info or {}
    user_id = auth_info.get("username")
    api_key = auth_info.get("password")
    if not user_id or not api_key:
        return None, None, "auth_info requires username and password"
    return str(user_id), str(api_key), None


def _jsc_timestamp():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+0000")


def _jsc_encode(params):
    from urllib.parse import quote
    parts = []
    for key in sorted(params.keys()):
        if key == "Signature":
            continue
        val = params[key]
        if val is None:
            continue
        parts.append(f"{quote(str(key), safe='')}={quote(str(val), safe='')}")
    return "&".join(parts)


def _jsc_sign(params, api_key):
    import hashlib
    import hmac
    encoded = _jsc_encode(params)
    return hmac.new(api_key.encode("utf-8"), encoded.encode("utf-8"), hashlib.sha256).hexdigest()


def _jsc_call(base, action, user_id, api_key, extra=None, body=None, timeout=30, verify_ssl=True):
    params = {
        "Action": action,
        "Format": "JSON",
        "Timestamp": _jsc_timestamp(),
        "UserID": user_id,
        "Version": SC_VERSION,
    }
    if extra:
        params.update({k: v for k, v in extra.items() if v is not None})
    params["Signature"] = _jsc_sign(params, api_key)
    if body is not None:
        return requests.post(f"{base}/", params=params, data=body, headers={"Content-Type": "application/xml"}, timeout=timeout, verify=verify_ssl)
    return requests.get(f"{base}/", params=params, timeout=timeout, verify=verify_ssl)


def _jsc_json(resp):
    try:
        return resp.json() if resp.text else {}
    except Exception:
        return {}


def _jsc_message(resp, data):
    if isinstance(data, dict) and data.get("ErrorResponse"):
        err = data["ErrorResponse"]
        head = err.get("Head") if isinstance(err, dict) else {}
        if isinstance(head, dict) and head.get("ErrorMessage"):
            return str(head["ErrorMessage"])
        return "Seller Center API error"
    if resp.status_code >= 400:
        return resp.text[:1000]
    return "ok"


def _jsc_feed_id(data):
    if isinstance(data, dict):
        success = data.get("SuccessResponse") or {}
        head = success.get("Head") if isinstance(success, dict) else {}
        if isinstance(head, dict) and head.get("RequestId"):
            return [head["RequestId"]]
    return []


def _jsc_product_xml(payload):
    import xml.etree.ElementTree as ET
    if isinstance(payload, str):
        return payload
    if not isinstance(payload, dict):
        return None
    if payload.get("xml"):
        return str(payload["xml"])
    products = payload.get("products") or payload.get("Products")
    if products is None and any(k in payload for k in ("SellerSku", "seller_sku", "Name", "name")):
        products = [payload]
    if not isinstance(products, list):
        return None
    root = ET.Element("Request")
    field_map = {
        "seller_sku": "SellerSku", "SellerSku": "SellerSku",
        "name": "Name", "Name": "Name",
        "primary_category": "PrimaryCategory", "PrimaryCategory": "PrimaryCategory",
        "description": "Description", "Description": "Description",
        "brand": "Brand", "Brand": "Brand",
        "price": "Price", "Price": "Price",
        "quantity": "Quantity", "Quantity": "Quantity",
        "parent_sku": "ParentSku", "ParentSku": "ParentSku",
    }
    for item in products:
        if not isinstance(item, dict):
            continue
        prod_el = ET.SubElement(root, "Product")
        for key, val in item.items():
            if key in ("xml", "products", "Products", "product_data", "ProductData"):
                continue
            tag = field_map.get(key, key)
            if isinstance(val, dict):
                nested = ET.SubElement(prod_el, tag)
                for nk, nv in val.items():
                    ET.SubElement(nested, str(nk)).text = str(nv)
            elif val is not None:
                ET.SubElement(prod_el, tag).text = str(val)
        pd = item.get("product_data") or item.get("ProductData")
        if isinstance(pd, dict):
            pd_el = ET.SubElement(prod_el, "ProductData")
            for nk, nv in pd.items():
                ET.SubElement(pd_el, str(nk)).text = str(nv)
    if not list(root):
        return None
    return '<?xml version="1.0" encoding="UTF-8"?>' + ET.tostring(root, encoding="unicode")
