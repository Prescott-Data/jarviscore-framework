from typing import Any, Dict, List, Optional

async def shopify_list_customers(shop: str='', limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Shopify Admin REST: list customers. Official: https://shopify.dev/docs/api/admin-rest/latest/resources/customer#get-customers"""
    try:
        root, err = _sh_root(base_url, shop)
        if err:
            return _sh_dataset([], 400, err)
        records, status, msg = await _sh_paginate(root, '/customers.json', 'customers', limit, timeout, verify_ssl)
        return _sh_dataset(records, status, msg)
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

def _sh_cap(limit):
    return min(max(int(limit or 25), 1), 250)

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

async def _sh_paginate(root, path, resource, limit, timeout, verify_ssl):
    headers, err = _sh_auth()
    if err:
        return ([], 401, err)
    cap = _sh_cap(limit)
    records = []
    url = root + path
    params = {'limit': min(cap, 250)}
    pages = 0
    while len(records) < cap and pages < 50:
        pages += 1
        resp = await nexus_call('GET', url, headers=headers, params=params)
        if resp['status_code'] >= 400:
            return (records, resp['status_code'], _sh_err(resp))
        try:
            data = resp['json']
        except Exception:
            data = {}
        batch = _sh_rows(data, resource)
        records.extend(batch)
        link = resp['headers'].get('Link') or ''
        nxt = None
        if 'rel="next"' in link:
            for part in link.split(','):
                if 'rel="next"' in part:
                    nxt = part.split(';')[0].strip().strip('<> ')
                    break
        if not nxt or not batch:
            break
        url = nxt
        params = None
    return (records[:cap], 200, 'ok')
