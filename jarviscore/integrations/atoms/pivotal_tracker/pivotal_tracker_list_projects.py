from typing import Any, Dict, List, Optional

async def pivotal_tracker_list_projects(limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """List active projects (offset/limit pagination). Official: https://www.pivotaltracker.com/help/api/rest/v5"""
    try:
        extra = None or None
        if not isinstance(extra, dict):
            extra = {}
        records, status, msg = await _pt_paginate('/projects', base_url, limit, timeout, verify_ssl, extra_params=extra)
        return _pt_dataset(records, status, msg)
    except Exception as e:
        return _pt_dataset([], 500, str(e))

def _pt_root(base_url):
    root = (base_url or None or None or None or 'https://www.pivotaltracker.com/services/v5').strip().rstrip('/')
    if '/services/v' not in root:
        root = root + '/services/v5'
    return (root, None)

def _pt_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _pt_cap(limit):
    return min(max(int(limit or 25), 1), 500)

def _pt_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _pt_err(resp, body=None):
    if isinstance(body, dict):
        err = body.get('error') or body.get('message')
        if err:
            return str(err)[:1000]
    return (resp['body'] if resp is not None else 'request failed')[:1000]

def _pt_items(data):
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        inner = data.get('data')
        if isinstance(inner, list):
            return [x for x in inner if isinstance(x, dict)]
        if inner is not None:
            return [inner] if isinstance(inner, dict) else []
        return [data]
    return []

async def _pt_request(method, url, params=None, json_body=None, timeout=30, verify_ssl=True):
    headers, err = _pt_auth(json_body=json_body is not None)
    if err:
        return (None, None, 401, err)
    kwargs = {'headers': headers, 'timeout': timeout, 'verify': verify_ssl}
    if method == 'get':
        resp = await nexus_call('GET', url, params=params)
    elif method == 'post':
        resp = await nexus_call('POST', url, params=params, json=json_body)
    elif method == 'put':
        resp = await nexus_call('PUT', url, params=params, json=json_body)
    else:
        return (None, None, 400, f'unsupported method {method}')
    try:
        body = resp['json'] if resp['content'] else {}
    except Exception:
        body = {}
    if resp['status_code'] >= 400:
        return (resp, body, resp['status_code'], _pt_err(resp, body))
    return (resp, body, resp['status_code'], 'ok')

async def _pt_paginate(path, base_url, limit, timeout, verify_ssl, extra_params=None):
    root, err = _pt_root(base_url)
    if err:
        return ([], 400, err)
    cap = _pt_cap(limit)
    records = []
    offset = 0
    status = 200
    msg = 'ok'
    while len(records) < cap:
        params = dict(extra_params or {})
        params['limit'] = min(200, cap - len(records))
        params['offset'] = offset
        resp, body, status, msg = await _pt_request('get', root + path, params=params, timeout=timeout, verify_ssl=verify_ssl)
        if status >= 400:
            return (records[:cap], status, msg)
        batch = _pt_items(body)
        records.extend(batch)
        returned_hdr = resp['headers'].get('X-Tracker-Pagination-Returned') if resp is not None else None
        total_hdr = resp['headers'].get('X-Tracker-Pagination-Total') if resp is not None else None
        returned = int(returned_hdr) if returned_hdr not in (None, '') else len(batch)
        total = int(total_hdr) if total_hdr not in (None, '') else offset + returned
        offset += returned
        if returned == 0 or offset >= total:
            break
    return (records[:cap], status, msg)
