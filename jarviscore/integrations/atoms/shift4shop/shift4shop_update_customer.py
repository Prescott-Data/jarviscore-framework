from typing import Any, Dict, List, Optional

async def shift4shop_update_customer(customer_id: str, payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Shift4Shop REST: update customer. Official: https://developers.3dcart.com/rest-api/customers"""
    try:
        if not customer_id:
            return _s4_provision({}, 400, 'customer_id is required')
        if not isinstance(payload, dict) or not payload:
            return _s4_provision({}, 400, 'payload is required')
        (root, err) = _s4_root(base_url)
        if err:
            return _s4_provision({}, 400, err)
        (headers, aerr) = _s4_auth()
        if aerr:
            return _s4_provision({}, 401, aerr)
        headers['Content-Type'] = 'application/json'
        resp = await nexus_call('PUT', root + '/Customers/' + str(customer_id), headers=headers, json=payload)
        try:
            data = resp['json'] if resp['content'] else {}
        except Exception:
            data = {}
        if resp['status_code'] >= 400:
            return _s4_provision(data if isinstance(data, dict) else {}, resp['status_code'], _s4_err(resp))
        return _s4_provision(data if isinstance(data, dict) else {}, resp['status_code'], 'ok', fallback_id=customer_id)
    except Exception as e:
        return _s4_provision({}, 500, str(e))

def _s4_root(base_url):
    root = (base_url or None or None or None or '').strip().rstrip('/')
    if not root:
        return (None, 'base_url is required (https://store.example.com)')
    if not root.endswith('/3dCartWebAPI/v1'):
        root = root + '/3dCartWebAPI/v1'
    return (root, None)

def _s4_auth():
    token = None or None
    if not token:
        return (None, 'auth_info.api_key is required')
    private_key = None or None or ''
    secure_url = (None or None or None or None or '').strip().rstrip('/')
    return ({'Accept': 'application/json', 'Content-Type': 'application/json', 'Token': str(token).strip(), 'PrivateKey': str(private_key).strip(), 'SecureURL': secure_url, 'Authorization': 'Bearer ' + str(token).strip()}, None)

def _s4_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get('CatalogID') or obj.get('OrderID') or obj.get('CustomerID') or fallback_id
    ids = [pid] if pid not in (None, '') else []
    rec = obj if obj else {'id': pid} if ids else {}
    return {'records': [rec] if rec else [], 'data_count': 1 if rec else 0, 'status': status, 'message': msg, 'provision_ids': ids}

def _s4_err(resp):
    return (resp['body'] or f"HTTP {resp['status_code']}")[:1000]
