from typing import Any, Dict, List, Optional
GORGIAS_API = 'https://your-domain.gorgias.com/api'

async def gorgias_list_conversations(limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """List Gorgias tickets (conversations) with cursor pagination. Official: https://developers.gorgias.com/reference/list-tickets"""
    try:
        (api, err) = _gorgias_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        (headers, basic, auth_err) = _gorgias_require_auth()
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        (records, status, message) = await _gorgias_cursor_paginate(f'{api}/tickets', headers, basic, limit, timeout, verify_ssl)
        return {'records': records, 'data_count': len(records), 'status': status, 'message': message}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _gorgias_api_root(base_url):
    root = (base_url or GORGIAS_API).rstrip('/')
    if not root.endswith('/api'):
        if _host_is(root, 'gorgias.com'):
            root = root + '/api'
        else:
            return (None, 'base_url must be https://{domain}.gorgias.com/api')
    return (root, None)

def _gorgias_require_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (None, None, 'auth_info requires username and password')

async def _gorgias_get(url, headers, basic, params, timeout, verify_ssl):
    return await nexus_call('GET', url, headers=headers, params=params)

async def _gorgias_cursor_paginate(url, headers, basic, limit, timeout, verify_ssl, extra_params=None):
    records = []
    cursor = None
    status = 0
    cap = min(max(int(limit or 25), 1), 100)
    extra_params = dict(extra_params or {})
    pages = 0
    while len(records) < cap and pages < 100:
        pages += 1
        params = {'limit': min(cap - len(records), 100)}
        params.update(extra_params)
        if cursor:
            params['cursor'] = cursor
        resp = await _gorgias_get(url, headers, basic, params, timeout, verify_ssl)
        status = resp['status_code']
        if status >= 400:
            return (records, status, resp['body'][:1000])
        data = resp['json'] if resp['body'] else {}
        batch = data.get('data') if isinstance(data, dict) else []
        if not isinstance(batch, list):
            batch = [batch] if isinstance(batch, dict) else []
        for item in batch:
            if isinstance(item, dict):
                records.append(item)
                if len(records) >= cap:
                    break
        meta = data.get('meta') if isinstance(data, dict) else {}
        cursor = meta.get('next_cursor') if isinstance(meta, dict) else None
        if not cursor or not batch:
            break
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
