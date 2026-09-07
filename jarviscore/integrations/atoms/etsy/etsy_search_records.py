from typing import Any, Dict, List, Optional
_ETSY_API_SUFFIX = '/v3/application'

async def etsy_search_records(query: str, limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Search active marketplace listings (GET /v3/application/listings/active?keywords=). Requires x-api-key (keystring:shared_secret) and OAuth Bearer token per Etsy Open API v3. Official: https://developers.etsy.com/documentation/reference#operation/findAllListingsActive"""
    try:
        if not query:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'query is required'}
        (api, err) = _etsy_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        (headers, auth_err) = _etsy_auth(require_oauth=False)
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        url = f'{api}/listings/active'
        params = {'keywords': query}
        (records, status, message) = await _etsy_paginate(url, headers, params, limit, timeout, verify_ssl)
        if message != 'ok':
            return {'records': records, 'data_count': len(records), 'status': status, 'message': message}
        return {'records': records, 'data_count': len(records), 'status': status, 'message': 'ok'}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _etsy_api_root(base_url: str):
    root = (base_url or '').rstrip('/')
    if not root:
        return (None, 'base_url is required (https://openapi.etsy.com/v3/application)')
    if not root.endswith('/v3/application'):
        if root.endswith('/v3'):
            root = f'{root}/application'
        elif _host_is(root, 'etsy.com') and _ETSY_API_SUFFIX not in root:
            return (None, 'base_url must be the Etsy Open API v3 root (https://openapi.etsy.com/v3/application)')
    return (root, None)

def _etsy_api_key():
    return None

def _etsy_auth(form=False, require_oauth=True):
    headers = {'Accept': 'application/json'}
    if form:
        headers['Content-Type'] = 'application/x-www-form-urlencoded; charset=utf-8'
    api_key = _etsy_api_key()
    if not api_key:
        return (None, 'auth_info.api_key is required')
    headers['x-api-key'] = str(api_key)
    if require_oauth:
        return (None, 'auth_info.access_token is required for this endpoint')
    return (headers, None)

def _etsy_results(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        results = data.get('results')
        if isinstance(results, list):
            return results
        for key in ('listing_id', 'receipt_id', 'user_id'):
            if data.get(key) is not None:
                return [data]
    return []

async def _etsy_paginate(url, headers, base_params, limit, timeout, verify_ssl):
    records = []
    cap = min(max(int(limit or 25), 1), 100)
    offset = 0
    status = 0
    while len(records) < cap:
        page_limit = min(cap - len(records), 100)
        params = dict(base_params or {})
        params['limit'] = page_limit
        params['offset'] = offset
        resp = await nexus_call('GET', url, headers=headers, params=params)
        status = resp['status_code']
        if status >= 400:
            return (records, status, resp['body'][:1000])
        data = resp['json'] if resp['body'] else {}
        batch = _etsy_results(data)
        for item in batch:
            if isinstance(item, dict):
                records.append(item)
                if len(records) >= cap:
                    return (records[:cap], status, 'ok')
        if len(batch) < page_limit:
            break
        offset += page_limit
        if offset > 100000:
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
