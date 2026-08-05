import requests
from typing import Any, Dict, List, Optional

# Jumia Seller Center API — http://sellerapi.sellercenter.jumia.com/categories/v2.7.11/sales-order-endpoints
JUMIA_SC_API = "http://sellerapi.sellercenter.jumia.com"
SC_VERSION = "1.0"
_STATUS_ACTIONS = {
    "ready_to_ship": "SetStatusToReadyToShip",
    "shipped": "SetStatusToShipped",
    "delivered": "SetStatusToDelivered",
    "canceled": "SetStatusToCanceled",
    "cancelled": "SetStatusToCanceled",
    "failed_delivery": "SetStatusToFailedDelivery",
    "packed_by_marketplace": "SetStatusToPackedByMarketplace",
}


def jumia_seller_center_update_order(auth_info: dict, order_id: str, payload: Dict[str, Any], timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Update order status via SetStatusTo* actions (XML body). Official: http://sellerapi.sellercenter.jumia.com/categories/v2.7.11/sales-order-endpoints"""
    try:
        if not order_id:
            return {"records": [], "data_count": 0, "status": 400, "message": "order_id is required"}
        payload = payload or {}
        action = payload.get("action")
        if not action:
            status_key = str(payload.get("status", "")).lower().replace(" ", "_")
            action = _STATUS_ACTIONS.get(status_key)
        if not action:
            return {"records": [], "data_count": 0, "status": 400, "message": "payload.action or payload.status is required (SetStatusTo* actions)"}
        base, err = _jsc_root(base_url)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err}
        user_id, api_key, cerr = _jsc_creds(auth_info)
        if cerr:
            return {"records": [], "data_count": 0, "status": 401, "message": cerr}
        body = _jsc_order_status_xml(order_id, payload)
        resp = _jsc_call(base, str(action), user_id, api_key, body=body, timeout=timeout, verify_ssl=verify_ssl)
        data = _jsc_json(resp)
        status = 400 if data.get("ErrorResponse") else resp.status_code
        if status >= 400:
            return {"records": [], "data_count": 0, "status": status, "message": _jsc_message(resp, data)}
        records = [{"order_id": order_id, "action": action}]
        return {"records": records, "data_count": 1, "status": status, "message": "ok", "provision_ids": [order_id]}
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


def _jsc_order_status_xml(order_id, payload):
    import xml.etree.ElementTree as ET
    if isinstance(payload, dict) and payload.get("xml"):
        return str(payload["xml"])
    root = ET.Element("Request")
    order_items = ET.SubElement(root, "OrderItemIds")
    item_ids = []
    if isinstance(payload, dict):
        item_ids = payload.get("order_item_ids") or payload.get("OrderItemIds") or []
        if isinstance(item_ids, str):
            item_ids = [item_ids]
    if not item_ids and order_id:
        item_ids = [order_id]
    for item_id in item_ids:
        ET.SubElement(order_items, "OrderItemId").text = str(item_id)
    return '<?xml version="1.0" encoding="UTF-8"?>' + ET.tostring(root, encoding="unicode")
