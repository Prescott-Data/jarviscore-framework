from typing import Any, Dict, List, Optional
NUTSHELL_RPC = 'https://app.nutshell.com/api/v1/json'

async def nutshell_list_contacts(limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """List Contacts via Nutshell JSON-RPC. Official: https://developers-rpc.nutshell.com/detail/class_core.html#findContacts"""
    try:
        (base, err) = _ns_root(base_url)
        if err:
            return _ns_dataset([], 400, err)
        (headers, aerr) = _ns_auth()
        if aerr:
            return _ns_dataset([], 401, aerr)
        params = {'orderBy': 'id', 'orderDirection': 'ASC', 'stubResponses': False}
        (records, status, msg) = await _ns_paginate(base, headers, 'findContacts', params, limit, timeout, verify_ssl)
        return _ns_dataset(records, status, msg)
    except Exception as e:
        return _ns_dataset([], 500, str(e))

def _ns_root(base_url):
    root = (base_url or NUTSHELL_RPC).rstrip('/')
    if 'nutshell.com' not in root:
        return (None, 'base_url must be https://app.nutshell.com/api/v1/json')
    if not root.endswith('/json'):
        if root.endswith('/api/v1'):
            root = root + '/json'
        elif '/api/' not in root:
            root = root + '/api/v1/json'
    return (root, None)

def _ns_auth():
    import base64
    return ({'Accept': 'application/json', 'Content-Type': 'application/json'}, None)

async def _ns_rpc(base, headers, method, params, timeout, verify_ssl, req_id=1):
    body = {'jsonrpc': '2.0', 'method': method, 'params': params or {}, 'id': req_id}
    resp = await nexus_call('POST', base, headers=headers, json=body)
    status = resp['status_code']
    try:
        payload = resp['json'] if resp['body'] else {}
    except Exception:
        payload = {}
    if status >= 400:
        msg = resp['body'][:1000]
        if isinstance(payload, dict):
            err = payload.get('error')
            if isinstance(err, dict):
                msg = str(err.get('message') or err.get('data') or err)[:1000]
        return (None, status, msg)
    if isinstance(payload, dict) and payload.get('error'):
        err = payload['error']
        msg = str(err.get('message') if isinstance(err, dict) else err)[:1000]
        return (None, 400, msg)
    result = payload.get('result') if isinstance(payload, dict) else None
    return (result, status, 'ok')

def _ns_records(result):
    if isinstance(result, list):
        return [r for r in result if isinstance(r, dict)]
    if isinstance(result, dict):
        if result.get('id') is not None:
            return [result]
        for key in ('contacts', 'accounts', 'leads', 'results', 'stubs'):
            val = result.get(key)
            if isinstance(val, list):
                return [r for r in val if isinstance(r, dict)]
    return []

def _ns_cap(limit):
    return min(max(int(limit or 25), 1), 100)

def _ns_dataset(records, status, msg):
    return {'records': records, 'data_count': len(records), 'status': status, 'message': msg}

async def _ns_paginate(base, headers, method, params, limit, timeout, verify_ssl):
    cap = _ns_cap(limit)
    page = 1
    records = []
    status = 200
    while len(records) < cap and page <= 50:
        p = dict(params or {})
        p['limit'] = min(cap - len(records), 100)
        p['page'] = page
        p.setdefault('stubResponses', False)
        (result, status, msg) = await _ns_rpc(base, headers, method, p, timeout, verify_ssl, req_id=page)
        if msg != 'ok':
            return (records, status, msg)
        batch = _ns_records(result)
        if not batch:
            break
        records.extend(batch)
        if len(batch) < p['limit']:
            break
        page += 1
    return (records[:cap], status, 'ok')
