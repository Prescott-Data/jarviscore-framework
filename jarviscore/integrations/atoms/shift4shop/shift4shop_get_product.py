from typing import Any, Dict, List, Optional

async def shift4shop_get_product(product_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Shift4Shop REST: get product. Official: https://developers.3dcart.com/rest-api/products"""
    try:
        if not product_id:
            return _s4_dataset([], 400, 'product_id is required')
        (root, err) = _s4_root(base_url)
        if err:
            return _s4_dataset([], 400, err)
        (headers, aerr) = _s4_auth()
        if aerr:
            return _s4_dataset([], 401, aerr)
        resp = await nexus_call('GET', root + '/Products/' + str(product_id), headers=headers)
        try:
            data = resp['json'] if resp['content'] else {}
        except Exception:
            data = {}
        if resp['status_code'] >= 400:
            return _s4_dataset([], resp['status_code'], _s4_err(resp))
        return _s4_dataset([data] if isinstance(data, dict) else [], resp['status_code'], 'ok')
    except Exception as e:
        return _s4_dataset([], 500, str(e))

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

def _s4_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _s4_err(resp):
    return (resp['body'] or f"HTTP {resp['status_code']}")[:1000]
