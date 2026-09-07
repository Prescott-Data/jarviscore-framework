from typing import Any, Dict, List, Optional
_TP_ROOT = 'https://example.tpondemand.com/api/v1'

async def targetprocess_list_projects(limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Targetprocess REST: list projects. Official: https://dev.targetprocess.com/docs/REST%20API"""
    try:
        root, err = _tp_root(base_url)
        if err:
            return _tp_dataset([], 400, err)
        records, status, msg = await _tp_paginate(f'{root}/Projects', {}, limit, timeout, verify_ssl)
        return _tp_dataset(records, status, msg)
    except Exception as e:
        return _tp_dataset([], 500, str(e))

def _tp_root(base_url):
    root = (base_url or None or None or '').strip().rstrip('/')
    if not root:
        return (None, 'base_url is required (https://{account}.tpondemand.com/api/v1)')
    if not root.endswith('/api/v1'):
        root = root + '/api/v1' if '/api/' not in root else root
    return (root, None)

def _tp_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _tp_cap(limit):
    return min(max(int(limit or 25), 1), 1000)

def _tp_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _tp_err(resp):
    try:
        data = resp['json']
        if isinstance(data, dict):
            return str(data.get('ErrorMessage') or data)[:1000]
    except Exception:
        pass
    return (resp['body'] or f'HTTP {resp['status_code']}')[:1000]

def _tp_items(data):
    if isinstance(data, dict):
        items = data.get('Items')
        if isinstance(items, list):
            return [x for x in items if isinstance(x, dict)]
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        return [data]
    return []

async def _tp_paginate(url, params, limit, timeout, verify_ssl):
    headers, err = _tp_auth()
    if err:
        return ([], 401, err)
    cap = _tp_cap(limit)
    records = []
    req_params = dict(params or {})
    req_params.setdefault('take', min(cap, 1000))
    req_params['access_token'] = str((None or {}).get('access_token') or '').strip()
    req_params.setdefault('format', 'json')
    skip = 0
    pages = 0
    while len(records) < cap and pages < 50:
        pages += 1
        req_params['skip'] = skip
        resp = await nexus_call('GET', url, headers=headers, params=req_params)
        if resp['status_code'] >= 400:
            return (records, resp['status_code'], _tp_err(resp))
        data = resp['json'] if resp['content'] else {}
        batch = _tp_items(data)
        records.extend(batch)
        if len(batch) < req_params.get('take', 25):
            break
        skip += len(batch)
    return (records[:cap], 200, 'ok')
