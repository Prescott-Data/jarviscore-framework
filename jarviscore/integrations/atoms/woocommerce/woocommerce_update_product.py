from typing import Any, Dict, List, Optional

async def woocommerce_update_product(product_id: str, name: str='', limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """woocommerce REST: update product. Official: https://woocommerce.github.io/woocommerce-rest-api-docs/"""
    try:
        root, err = _root(base_url)
        if err:
            return _provision({}, 400, err)
        if not product_id:
            return _provision({}, 400, 'product_id is required')
        headers, aerr = _auth()
        if isinstance(headers, str) or aerr:
            return _provision({}, 401, aerr or headers)
        auth = headers if isinstance(headers, tuple) else None
        hdrs = headers if isinstance(headers, dict) else {'Accept': 'application/json'}
        payload = {'name': name} if name else {}
        resp = await nexus_call('PUT', root + '/products/' + str(product_id), headers=hdrs, json=payload)
        if resp['status_code'] >= 400:
            return _provision({}, resp['status_code'], _err(resp))
        data = resp['json'] if resp['content'] else {}
        return _provision(data if isinstance(data, dict) else {}, resp['status_code'], 'ok', fallback_id=product_id)
    except Exception as e:
        return _provision({}, 500, str(e))

def _root(base_url):
    root = (base_url or None or 'https://example.com/wp-json/wc/v3').strip().rstrip('/')
    if not root:
        return (None, 'base_url is required')
    return (root, None)

def _auth():
    return (None, 'auth_info requires username and password')

def _provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get('id') or fallback_id
    ids = [pid] if pid not in (None, '') else []
    rec = obj if obj else {'id': pid} if ids else {}
    return {'records': [rec] if rec else [], 'data_count': 1 if rec else 0, 'status': status, 'message': msg, 'provision_ids': ids}

def _err(resp):
    return (resp['body'] or 'HTTP ' + str(resp['status_code']))[:1000]
