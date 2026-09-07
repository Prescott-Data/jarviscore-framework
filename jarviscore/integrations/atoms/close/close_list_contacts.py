from typing import Any, Dict, List, Optional
CLOSE_API = 'https://api.close.com/api/v1'

async def close_list_contacts(limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """List contacts from Close CRM. HTTP Basic API key (username, empty password). Official: https://developer.close.com/"""
    try:
        api = _close_api_root(base_url)
        (headers, basic, auth_err) = _close_auth()
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        (records, status, message) = await _close_paginate(f'{api}/contact/', headers, basic, limit, timeout, verify_ssl)
        return {'records': records, 'data_count': len(records), 'status': status, 'message': message}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _close_api_root(base_url):
    root = (base_url or CLOSE_API).rstrip('/')
    if root.endswith('/api/v1'):
        return root
    if root.endswith('/api'):
        return root + '/v1'
    if _host_is(root, 'api.close.com') and '/api/v1' not in root:
        return root + '/api/v1' if not root.endswith('/v1') else root
    if '/api/v1' not in root:
        return root + '/api/v1'
    return root

def _close_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (None, None, 'auth_info requires api_key (HTTP Basic, empty password)')

async def _close_get(url, headers, basic, params, timeout, verify_ssl):
    return await nexus_call('GET', url, headers=headers, params=params)

def _close_records_from(data, single=False):
    if single:
        if isinstance(data, dict):
            if isinstance(data.get('data'), dict):
                return [data['data']]
            if data.get('id') is not None:
                return [data]
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        items = data.get('data')
        if isinstance(items, list):
            return items
    return []

async def _close_paginate(url, headers, basic, limit, timeout, verify_ssl, extra=None):
    records = []
    skip = 0
    status = 0
    extra = extra or {}
    page_size = min(max(int(limit), 1), 100)
    while len(records) < limit:
        params = {'_limit': min(page_size, limit - len(records)), '_skip': skip}
        params.update(extra)
        resp = await _close_get(url, headers, basic, params, timeout, verify_ssl)
        status = resp['status_code']
        if status >= 400:
            return (records, status, resp['body'][:1000])
        data = resp['json'] if resp['body'] else {}
        batch = _close_records_from(data)
        if not batch:
            break
        for item in batch:
            if isinstance(item, dict):
                records.append(item)
                if len(records) >= limit:
                    break
        has_more = isinstance(data, dict) and data.get('has_more')
        skip += len(batch)
        if not has_more or len(batch) < params['_limit']:
            break
        if skip > 50000:
            break
    return (records[:limit], status, 'ok')

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
