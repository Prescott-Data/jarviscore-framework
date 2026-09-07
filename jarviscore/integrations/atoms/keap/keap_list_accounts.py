from typing import Any, Dict, List, Optional
KEAP_API = 'https://api.infusionsoft.com/crm/rest/v2'

async def keap_list_accounts(limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """List Keap accounts. Official: https://developer.keap.com/docs/restv2/"""
    try:
        api, err = _kp_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        headers, auth_err = _kp_auth()
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        records, status, message = await _kp_paginate(f'{api}/companies', headers, limit, timeout, verify_ssl)
        return {'records': records, 'data_count': len(records), 'status': status, 'message': message}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _kp_api_root(base_url):
    root = (base_url or KEAP_API).rstrip('/')
    if '/rest/v2' not in root:
        if _host_is(root, 'infusionsoft.com', 'keap.com'):
            root = root + '/crm/rest/v2' if '/crm' not in root else root + '/rest/v2' if not root.endswith('/v2') else root
        else:
            return (None, 'base_url must be https://api.infusionsoft.com/crm/rest/v2')
    return (root, None)

def _kp_auth():
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
    return (headers, None)

async def _kp_get(url, headers, params, timeout, verify_ssl):
    return await nexus_call('GET', url, headers=headers, params=params)

async def _kp_paginate(url, headers, limit, timeout, verify_ssl, extra=None):
    records = []
    token = None
    status = 0
    cap = min(max(int(limit or 25), 1), 1000)
    extra = dict(extra or {})
    pages = 0
    while len(records) < cap and pages < 100:
        pages += 1
        params = {'page_size': min(cap - len(records), 1000)}
        params.update(extra)
        if token:
            params['page_token'] = token
        resp = await _kp_get(url, headers, params, timeout, verify_ssl)
        status = resp['status_code']
        if status >= 400:
            return (records, status, resp['body'][:1000])
        data = resp['json'] if resp['body'] else {}
        batch = data.get('contacts') or data.get('companies') or data.get('opportunities') or data.get('records') or []
        if isinstance(data, list):
            batch = data
        if not isinstance(batch, list):
            batch = [batch] if isinstance(batch, dict) else []
        for item in batch:
            if isinstance(item, dict):
                records.append(item)
                if len(records) >= cap:
                    break
        token = data.get('next_page_token') if isinstance(data, dict) else None
        if not token or not batch:
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
