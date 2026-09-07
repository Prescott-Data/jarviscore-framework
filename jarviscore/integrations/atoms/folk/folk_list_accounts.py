from typing import Any, Dict, List, Optional
_FOLK_API_HOST = 'https://api.folk.app'

async def folk_list_accounts(limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """List companies (GET /v1/companies). Catalog account → Folk company. Bearer API key in Authorization header per Folk External API. Official: https://developer.folk.app/"""
    try:
        api, err = _folk_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        headers, auth_err = _folk_auth()
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        records, status, message = await _folk_paginate(f'{api}/companies', headers, {}, limit, timeout, verify_ssl)
        if message != 'ok':
            return {'records': records, 'data_count': len(records), 'status': status, 'message': message}
        return {'records': records, 'data_count': len(records), 'status': status, 'message': 'ok'}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _folk_api_root(base_url: str):
    root = (base_url or _FOLK_API_HOST).rstrip('/')
    if not root:
        return (None, 'base_url is required (https://api.folk.app)')
    if root.endswith('/v1'):
        root = root[:-3]
    if not root.endswith('folk.app'):
        return (None, 'base_url must be the Folk API root (https://api.folk.app)')
    return (f'{root}/v1', None)

def _folk_auth(json_body: bool=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _folk_list_items(data):
    if not isinstance(data, dict):
        return ([], None)
    inner = data.get('data')
    if not isinstance(inner, dict):
        return ([], None)
    items = inner.get('items')
    batch = items if isinstance(items, list) else []
    pag = inner.get('pagination') if isinstance(inner.get('pagination'), dict) else {}
    nxt = pag.get('nextLink')
    return (batch, nxt if isinstance(nxt, str) and nxt.startswith('http') else None)

async def _folk_paginate(url, headers, params, limit, timeout, verify_ssl):
    records = []
    cap = min(max(int(limit or 25), 1), 100)
    next_url = None
    status = 0
    pages = 0
    while len(records) < cap and pages < 50:
        pages += 1
        page_limit = min(cap - len(records), 100)
        req_params = None if next_url else dict(params or {})
        if req_params is not None:
            req_params['limit'] = page_limit
        resp = await nexus_call('GET', next_url or url, headers=headers, params=req_params)
        status = resp['status_code']
        if status >= 400:
            return (records, status, resp['body'][:1000])
        data = resp['json'] if resp['body'] else {}
        batch, next_url = _folk_list_items(data)
        for item in batch:
            if isinstance(item, dict):
                records.append(item)
                if len(records) >= cap:
                    return (records[:cap], status, 'ok')
        if not next_url or len(batch) < page_limit:
            break
    return (records[:cap], status, 'ok')
