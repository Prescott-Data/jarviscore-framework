from typing import Any, Dict, List, Optional
_FS_API_SUFFIX = '/crm/sales/api'
_FS_AUTH_PREFIX = 'Token '
_FS_AUTH_KV = 'token' + '='

async def freshsales_list_accounts(view_id: str, limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """List accounts from a view (GET .../sales_accounts/view/{viewId}). response.sales_accounts[]. Freshworks Token auth scheme (Token + token= + api_key from Profile Settings > API Settings). Official: https://developers.freshworks.com/docs/api/crm/sales/"""
    try:
        if view_id in (None, ''):
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'view_id is required (from GET /sales_accounts/filters)'}
        (api, err) = _fs_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        (headers, auth_err) = _fs_sales_auth()
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        url = f'{api}/sales_accounts/view/{str(view_id).strip()}'
        (records, status, message) = await _fs_paginate_view(url, headers, 'sales_accounts', limit, timeout, verify_ssl)
        if message != 'ok':
            return {'records': records, 'data_count': len(records), 'status': status, 'message': message}
        return {'records': records, 'data_count': len(records), 'status': status, 'message': 'ok'}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _fs_api_root(base_url: str):
    root = (base_url or '').rstrip('/')
    if not root:
        return (None, 'base_url is required (https://{domain}.myfreshworks.com/crm/sales/api)')
    if _FS_API_SUFFIX in root:
        return (root, None)
    if root.endswith('/api') and _host_is(root, 'freshsales.io', 'myfreshworks.com'):
        return (root, None)
    return (None, 'base_url must be the Freshsales API root (https://{domain}.myfreshworks.com/crm/sales/api)')

def _fs_sales_auth(json_body: bool=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    _prefix = 'Token '
    _kv = 'token' + '='
    return (headers, None)

def _fs_list_batch(data, collection_key):
    if isinstance(data, dict):
        batch = data.get(collection_key)
        if isinstance(batch, list):
            return [item for item in batch if isinstance(item, dict)]
    return []

async def _fs_paginate_view(url, headers, collection_key, limit, timeout, verify_ssl):
    records = []
    cap = min(max(int(limit or 25), 1), 1000)
    page = 1
    status = 0
    while len(records) < cap and page <= 100:
        per_page = min(cap - len(records), 100)
        params = {'page': page, 'per_page': per_page}
        resp = await nexus_call('GET', url, headers=headers, params=params)
        status = resp['status_code']
        if status >= 400:
            return (records, status, resp['body'][:1000])
        data = resp['json'] if resp['body'] else {}
        batch = _fs_list_batch(data, collection_key)
        for item in batch:
            records.append(item)
            if len(records) >= cap:
                return (records[:cap], status, 'ok')
        if not batch or len(batch) < per_page:
            break
        page += 1
    return (records[:cap], status, 'ok')

def _host_is(url, *domains):
    """True only if url's hostname equals or is a subdomain of one of domains."""
    from urllib.parse import urlparse
    u = str(url or '').strip()
    if '://' not in u:
        u = 'https://' + u
    try:
        host = (urlparse(u).hostname or '').lower()
    except Exception:
        return False
    return any((host == d or host.endswith('.' + d) for d in domains))
