from typing import Any, Dict, List, Optional
XERO_API = 'https://api.xero.com/api.xro/2.0'

async def xero_search_records(query: str, tenant_id: str='', limit: int=100, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """xero REST: search. Official: https://developer.xero.com/documentation/api/accounting/overview"""
    try:
        if not query:
            return _x_dataset([], 400, 'query is required')
        root, err = _x_root(base_url)
        if err:
            return _x_dataset([], 400, err)
        headers, aerr = _x_headers(tenant_id)
        if aerr:
            return _x_dataset([], 401, aerr)
        records, status, msg = await _x_paginate(root, 'Contacts', 'Contacts', headers, limit, {'searchTerm': query}, timeout, verify_ssl)
        return _x_dataset(records, status, msg)
    except Exception as e:
        return _x_dataset([], 500, str(e))

def _x_root(base_url):
    root = (base_url or None or XERO_API).strip().rstrip('/')
    if 'xero.com' not in root:
        return (None, 'base_url must be https://api.xero.com/api.xro/2.0')
    return (root, None)

def _x_headers(tenant_id, json_body=False):
    tenant = tenant_id or None
    if not tenant:
        return (None, 'tenant_id is required (Xero-tenant-id header; from GET /connections)')
    headers = {'Xero-tenant-id': str(tenant), 'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _x_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _x_records(body, key):
    if isinstance(body, dict):
        val = body.get(key)
        if isinstance(val, list):
            return [r for r in val if isinstance(r, dict)]
        if isinstance(val, dict):
            return [val]
    return []

def _x_err(resp):
    try:
        data = resp['json']
        if isinstance(data, dict):
            msg = data.get('Message') or data.get('message')
            elems = data.get('Elements')
            if isinstance(elems, list) and elems:
                ve = elems[0].get('ValidationErrors') if isinstance(elems[0], dict) else None
                if isinstance(ve, list) and ve:
                    return str(ve[0].get('Message') or ve[0])[:1000]
            if msg:
                return str(msg)[:1000]
    except Exception:
        pass
    return (resp['body'] or f'HTTP {resp['status_code']}')[:1000]

async def _x_paginate(root, resource, key, headers, limit, extra_params, timeout, verify_ssl):
    cap = min(max(int(limit or 25), 1), 1000)
    out: List[Dict[str, Any]] = []
    page = 1
    while len(out) < cap and page <= 50:
        params = dict(extra_params or {})
        params['page'] = page
        resp = await nexus_call('GET', f'{root}/{resource}', headers=headers, params=params)
        if resp['status_code'] >= 400:
            return (out, resp['status_code'], _x_err(resp))
        data = resp['json'] if resp['content'] else {}
        batch = _x_records(data, key)
        if not batch:
            break
        out.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return (out[:cap], 200, 'ok')
