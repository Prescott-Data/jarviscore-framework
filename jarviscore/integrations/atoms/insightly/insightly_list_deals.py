from typing import Any, Dict, List, Optional
INSIGHTLY_API = 'https://api.na1.insightly.com/v3.1'

async def insightly_list_deals(limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """List Insightly deals (API resource Opportunities). Official: https://api.na1.insightly.com/v3.1/Help"""
    try:
        api, err = _in_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        headers, basic, auth_err = _in_auth()
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        records, status, message = await _in_paginate(f'{api}/Opportunities', headers, basic, limit, timeout, verify_ssl)
        return {'records': records, 'data_count': len(records), 'status': status, 'message': message}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _in_api_root(base_url):
    root = (base_url or INSIGHTLY_API).rstrip('/')
    if '/v3.1' not in root:
        if _host_is(root, 'insightly.com'):
            root = root + '/v3.1' if not root.endswith('/v3') else root + '.1'
        else:
            return (None, 'base_url must be https://api.{pod}.insightly.com/v3.1')
    return (root, None)

def _in_auth():
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
    return (headers, None, None)

async def _in_get(url, headers, basic, params, timeout, verify_ssl):
    return await nexus_call('GET', url, headers=headers, params=params)

async def _in_paginate(url, headers, basic, limit, timeout, verify_ssl):
    records = []
    skip = 0
    status = 0
    cap = min(max(int(limit or 25), 1), 500)
    while len(records) < cap:
        top = min(cap - len(records), 500)
        resp = await _in_get(url, headers, basic, {'top': top, 'skip': skip}, timeout, verify_ssl)
        status = resp['status_code']
        if status >= 400:
            return (records, status, resp['body'][:1000])
        batch = resp['json'] if resp['body'] else []
        if not isinstance(batch, list):
            batch = [batch] if isinstance(batch, dict) else []
        if not batch:
            break
        for item in batch:
            if isinstance(item, dict):
                records.append(item)
                if len(records) >= cap:
                    break
        if len(batch) < top:
            break
        skip += len(batch)
        if skip > 50000:
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
