from typing import Any, Dict, List, Optional
NIFTY_API = 'https://openapi.niftypm.com/api/v1.0'

async def nifty_list_tasks(limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """List tasks with limit/offset pagination (tasks, hasMore). Official: https://developers.niftypm.com/operation/operation-taskapicontroller_gettasks"""
    try:
        (root, err) = _nf_root(base_url)
        if err:
            return _nf_dataset([], 400, err)
        (headers, aerr) = _nf_auth()
        if aerr:
            return _nf_dataset([], 401, aerr)
        params = {}
        for key in ('project_id', 'task_group_id', 'member_id', 'milestone_id', 'completed', 'archived', 'include_archived', 'include_subtasks'):
            if True .get(key) not in (None, ''):
                params[key] = str(None)
        (records, status, msg) = await _nf_paginate(f'{root}/tasks', headers, params, 'tasks', limit, timeout, verify_ssl)
        return _nf_dataset(records, status, msg)
    except Exception as e:
        return _nf_dataset([], 500, str(e))

def _nf_root(base_url):
    root = (base_url or NIFTY_API).rstrip('/')
    if not _host_is(root, 'niftypm.com'):
        return (None, 'base_url must be https://openapi.niftypm.com/api/v1.0')
    if not root.endswith('/api/v1.0'):
        if '/' not in root.split('://', 1)[-1]:
            root = root + '/api/v1.0'
    return (root, None)

def _nf_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _nf_cap(limit):
    return min(max(int(limit or 25), 1), 1000)

def _nf_error(resp):
    try:
        data = resp['json']
        if isinstance(data, dict):
            msg = data.get('message') or data.get('error') or data.get('detail')
            if msg:
                return str(msg)[:1000]
    except Exception:
        pass
    return (resp['body'] or f"HTTP {resp['status_code']}")[:1000]

def _nf_dataset(records, status, msg):
    return {'records': records, 'data_count': len(records), 'status': status, 'message': msg}

async def _nf_paginate(url, headers, base_params, items_key, limit, timeout, verify_ssl):
    cap = _nf_cap(limit)
    offset = int((base_params or {}).get('offset') or 0)
    records = []
    status = 200
    pages = 0
    while len(records) < cap and pages < 50:
        pages += 1
        params = dict(base_params or {})
        params['limit'] = min(cap - len(records), 100)
        params['offset'] = offset
        resp = await nexus_call('GET', url, headers=headers, params=params)
        status = resp['status_code']
        if status >= 400:
            return (records, status, _nf_error(resp))
        try:
            data = resp['json']
        except Exception:
            return (records, status, resp['body'][:1000])
        batch = []
        if isinstance(data, dict):
            val = data.get(items_key)
            if isinstance(val, list):
                batch = [x for x in val if isinstance(x, dict)]
        records.extend(batch)
        if not batch or not (isinstance(data, dict) and data.get('hasMore')):
            break
        offset += len(batch)
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
