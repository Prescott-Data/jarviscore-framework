from typing import Any, Dict, List, Optional

async def shopify_update_product(product_id: str, payload: Dict[str, Any], shop: str='', timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Shopify Admin REST: update product. Official: https://shopify.dev/docs/api/admin-rest/latest/resources/product#put-products-product-id"""
    try:
        if not product_id:
            return _sh_provision({}, 400, 'product_id is required', 'product')
        if not isinstance(payload, dict) or not payload:
            return _sh_provision({}, 400, 'payload is required', 'product')
        (root, err) = _sh_root(base_url, shop)
        if err:
            return _sh_provision({}, 400, err, 'product')
        (headers, aerr) = _sh_auth()
        if aerr:
            return _sh_provision({}, 401, aerr, 'product')
        headers['Content-Type'] = 'application/json'
        body = payload if 'product' in payload else {'product': payload}
        resp = await nexus_call('PUT', root + '/products/{product_id}.json'.format(**locals()), headers=headers, json=body)
        try:
            data = resp['json'] if resp['content'] else {}
        except Exception:
            data = {}
        if resp['status_code'] >= 400:
            return _sh_provision(data, resp['status_code'], _sh_err(resp), 'product', fallback_id=product_id)
        return _sh_provision(data, resp['status_code'], 'ok', 'product', fallback_id=product_id)
    except Exception as e:
        return _sh_provision({}, 500, str(e), 'product')

def _sh_root(base_url, shop):
    shop = (shop or None or None or '').strip().rstrip('/')
    if shop and (not shop.startswith('http')):
        shop = f'https://{shop}' if shop.endswith('.myshopify.com') else f'https://{shop}.myshopify.com'
    root = (base_url or None or shop or None or '').strip().rstrip('/')
    if not root:
        return (None, 'base_url or shop is required (https://{shop}.myshopify.com)')
    if not root.endswith('/admin/api'):
        ver = None or '2024-04'
        if '/admin/api/' not in root:
            root = root + f'/admin/api/{ver}'
    return (root, None)

def _sh_auth():
    return ({'Accept': 'application/json'}, None)

def _sh_provision(data, status, msg, resource, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    inner = obj.get(resource) if isinstance(obj.get(resource), dict) else obj
    pid = (inner or {}).get('id') or fallback_id
    ids = [pid] if pid not in (None, '') else []
    rec = inner if inner else {'id': pid} if ids else {}
    return {'records': [rec] if rec else [], 'data_count': 1 if rec else 0, 'status': status, 'message': msg, 'provision_ids': ids}

def _sh_err(resp):
    try:
        data = resp['json']
        if isinstance(data, dict):
            errs = data.get('errors')
            if errs:
                return str(errs)[:1000]
    except Exception:
        pass
    return (resp['body'] or f"HTTP {resp['status_code']}")[:1000]
