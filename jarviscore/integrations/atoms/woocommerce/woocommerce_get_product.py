from typing import Any, Dict, List, Optional

async def woocommerce_get_product(product_id: str, limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """woocommerce REST: get product. Official: https://woocommerce.github.io/woocommerce-rest-api-docs/"""
    try:
        root, err = _root(base_url)
        if err:
            return _dataset([], 400, err)
        if not product_id:
            return _dataset([], 400, 'product_id is required')
        headers, aerr = _auth()
        if isinstance(headers, str) or aerr:
            return _dataset([], 401, aerr or headers)
        auth = headers if isinstance(headers, tuple) else None
        hdrs = headers if isinstance(headers, dict) else {'Accept': 'application/json'}
        resp = await nexus_call('GET', root + '/products/' + str(product_id), headers=hdrs)
        if resp['status_code'] >= 400:
            return _dataset([], resp['status_code'], _err(resp))
        data = resp['json'] if resp['content'] else {}
        return _dataset(data if isinstance(data, list) else [data] if isinstance(data, dict) else [], resp['status_code'], 'ok')
    except Exception as e:
        return _dataset([], 500, str(e))

def _root(base_url):
    root = (base_url or None or 'https://example.com/wp-json/wc/v3').strip().rstrip('/')
    if not root:
        return (None, 'base_url is required')
    return (root, None)

def _auth():
    return (None, 'auth_info requires username and password')

def _dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _err(resp):
    return (resp['body'] or 'HTTP ' + str(resp['status_code']))[:1000]
