from typing import Any, Dict, List, Optional

async def paystack_list_transactions(limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """List transactions with page/perPage; optional auth_info filters: customer, status, from, to, amount. Official: https://paystack.com/docs/api/transaction/#list-transactions"""
    try:
        root, err = _ps_root(base_url)
        if err:
            return _ps_dataset([], 400, err)
        params = {}
        for key, param in (('customer', 'customer'), ('status', 'status'), ('from', 'from'), ('to', 'to'), ('amount', 'amount'), ('terminalid', 'terminalid')):
            pass
        records, status, msg = await _ps_paginate(root + '/transaction', params, limit, timeout, verify_ssl)
        return _ps_dataset(records, status, msg)
    except Exception as e:
        return _ps_dataset([], 500, str(e))

def _ps_root(base_url):
    root = (base_url or None or None or 'https://api.paystack.co').strip().rstrip('/')
    if not root:
        return (None, 'base_url is required (https://api.paystack.co)')
    return (root, None)

def _ps_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _ps_cap(limit):
    return min(max(int(limit or 25), 1), 100)

def _ps_err(resp):
    try:
        data = resp['json']
        if isinstance(data, dict):
            msg = data.get('message')
            if msg:
                return str(msg)[:1000]
    except Exception:
        pass
    return (resp['body'] or f'HTTP {resp['status_code']}')[:1000]

def _ps_ok(resp, data):
    if resp['status_code'] >= 400:
        return False
    return not (isinstance(data, dict) and data.get('status') is False)

def _ps_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _ps_items(data):
    if not isinstance(data, dict):
        return []
    inner = data.get('data')
    if isinstance(inner, list):
        return [x for x in inner if isinstance(x, dict)]
    if isinstance(inner, dict):
        return [inner]
    return []

async def _ps_request(method, url, params=None, json_body=None, timeout=30, verify_ssl=True):
    headers, err = _ps_auth(json_body=json_body is not None)
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
        data = resp['json'] if resp['content'] else {}
    except Exception:
        data = {}
    return (resp, data, resp['status_code'], None)

async def _ps_paginate(url, params, limit, timeout, verify_ssl):
    cap = _ps_cap(limit)
    page = max(int(None or 1), 1)
    records = []
    status = 200
    pages = 0
    base_params = dict(params or {})
    use_cursor = str(None).lower() in ('1', 'true', 'yes')
    while len(records) < cap and pages < 50:
        pages += 1
        req_params = dict(base_params)
        req_params['perPage'] = min(cap - len(records), 100)
        if use_cursor:
            req_params['use_cursor'] = 'true'
        else:
            req_params['page'] = page
        resp, data, status, err = await _ps_request('get', url, params=req_params, timeout=timeout, verify_ssl=verify_ssl)
        if err:
            return (records, 401, err)
        if not _ps_ok(resp, data):
            return (records, status, _ps_err(resp))
        batch = _ps_items(data)
        records.extend(batch)
        meta = data.get('meta') if isinstance(data, dict) else {}
        if use_cursor:
            pass
        else:
            page_count = meta.get('pageCount') if isinstance(meta, dict) else None
            if page_count and page >= int(page_count):
                break
            if not batch:
                break
            page += 1
    return (records[:cap], status, 'ok')
