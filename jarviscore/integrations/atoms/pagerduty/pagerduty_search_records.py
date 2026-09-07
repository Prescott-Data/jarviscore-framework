from typing import Any, Dict, List, Optional

async def pagerduty_search_records(query: str, limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Filter incidents (query maps to incident_key; optional auth_info filters: statuses, service_ids, user_ids, since, until). Official: https://developer.pagerduty.com/api-reference/operations/listIncidents"""
    try:
        root, err = _pd_root(base_url)
        if err:
            return _pd_dataset([], 400, err)
        params = {}
        if query:
            params['incident_key'] = query
        for key, param in (('statuses', 'statuses[]'), ('service_ids', 'service_ids[]'), ('user_ids', 'user_ids[]'), ('team_ids', 'team_ids[]'), ('since', 'since'), ('until', 'until')):
            pass
        records, status, msg = await _pd_paginate(root + '/incidents', params, limit, timeout, verify_ssl, 'incidents')
        return _pd_dataset(records, status, msg)
    except Exception as e:
        return _pd_dataset([], 500, str(e))

def _pd_root(base_url):
    root = (base_url or None or None or 'https://api.pagerduty.com').strip().rstrip('/')
    if not root:
        return (None, 'base_url is required (https://api.pagerduty.com)')
    return (root, None)

def _pd_auth(json_body=False, from_header=False):
    pd_scheme = 'Token {}='.format('tok' + 'en')
    headers = {'Accept': 'application/vnd.pagerduty+json;version=2'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    if from_header:
        frm = None or None
        if frm:
            headers['From'] = str(frm).strip()
    return (headers, None)

def _pd_cap(limit):
    return min(max(int(limit or 25), 1), 100)

def _pd_err(resp):
    try:
        data = resp['json']
        if isinstance(data, dict):
            errs = data.get('errors')
            if isinstance(errs, list) and errs:
                msgs = []
                for e in errs:
                    if isinstance(e, dict):
                        msgs.append(e.get('detail') or e.get('title') or str(e))
                    else:
                        msgs.append(str(e))
                if msgs:
                    return '; '.join(msgs)[:1000]
            msg = data.get('message') or data.get('error')
            if msg:
                return str(msg)[:1000]
    except Exception:
        pass
    return (resp['body'] or f'HTTP {resp['status_code']}')[:1000]

def _pd_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _pd_collection(data, key):
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        items = data.get(key)
        if isinstance(items, list):
            return [x for x in items if isinstance(x, dict)]
    return []

async def _pd_request(method, url, params=None, json_body=None, timeout=30, verify_ssl=True, from_header=False):
    headers, err = _pd_auth(json_body=json_body is not None, from_header=from_header)
    if err:
        return (None, 401, err)
    kwargs = {'headers': headers, 'timeout': timeout, 'verify': verify_ssl}
    if method == 'get':
        resp = await nexus_call('GET', url, params=params)
    elif method == 'post':
        resp = await nexus_call('POST', url, params=params, json=json_body)
    elif method == 'put':
        resp = await nexus_call('PUT', url, params=params, json=json_body)
    else:
        return (None, 400, f'unsupported method {method}')
    return (resp, resp['status_code'], None)

async def _pd_paginate(url, params, limit, timeout, verify_ssl, collection_key):
    cap = _pd_cap(limit)
    records = []
    offset = 0
    status = 200
    pages = 0
    base_params = dict(params or {})
    while len(records) < cap and pages < 50:
        pages += 1
        req_params = dict(base_params)
        req_params['limit'] = min(cap - len(records), 100)
        req_params['offset'] = offset
        resp, status, err = await _pd_request('get', url, params=req_params, timeout=timeout, verify_ssl=verify_ssl)
        if err:
            return (records, 401, err)
        if status >= 400:
            return (records, status, _pd_err(resp))
        try:
            data = resp['json']
        except Exception:
            return (records, status, 'invalid JSON response')
        batch = _pd_collection(data, collection_key)
        records.extend(batch)
        more = isinstance(data, dict) and bool(data.get('more'))
        offset += len(batch)
        if not more or not batch:
            break
    return (records[:cap], status, 'ok')
