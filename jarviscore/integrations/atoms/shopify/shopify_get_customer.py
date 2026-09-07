from typing import Any, Dict, List, Optional

async def shopify_get_customer(customer_id: str, shop: str='', timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Shopify Admin REST: get customer. Official: https://shopify.dev/docs/api/admin-rest/latest/resources/customer#get-customers-customer-id"""
    try:
        if not customer_id:
            return _sh_dataset([], 400, 'customer_id is required')
        root, err = _sh_root(base_url, shop)
        if err:
            return _sh_dataset([], 400, err)
        headers, aerr = _sh_auth()
        if aerr:
            return _sh_dataset([], 401, aerr)
        resp = await nexus_call('GET', root + '/customers/{customer_id}.json'.format(**locals()), headers=headers)
        try:
            data = resp['json'] if resp['content'] else {}
        except Exception:
            data = {}
        if resp['status_code'] >= 400:
            return _sh_dataset([], resp['status_code'], _sh_err(resp))
        return _sh_dataset(_sh_rows(data, 'customers'), resp['status_code'], 'ok')
    except Exception as e:
        return _sh_dataset([], 500, str(e))

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

def _sh_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _sh_err(resp):
    try:
        data = resp['json']
        if isinstance(data, dict):
            errs = data.get('errors')
            if errs:
                return str(errs)[:1000]
    except Exception:
        pass
    return (resp['body'] or f'HTTP {resp['status_code']}')[:1000]

def _sh_rows(data, resource):
    if isinstance(data, dict):
        items = data.get(resource)
        if isinstance(items, list):
            return [x for x in items if isinstance(x, dict)]
        one = data.get(resource.rstrip('s'))
        if isinstance(one, dict):
            return [one]
    return []
