from typing import Any, Dict, List, Optional

async def salesflare_list_accounts(limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """List accounts. Official: https://api.salesflare.com/docs"""
    try:
        records, status, msg = await _sf_list('/accounts', 'accounts', base_url, limit, timeout, verify_ssl)
        return _sf_dataset(records, status, msg)
    except Exception as e:
        return _sf_dataset([], 500, str(e))

def _sf_root(base_url):
    root = (base_url or None or None or 'https://api.salesflare.com').strip().rstrip('/')
    return (root, None)

def _sf_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _sf_cap(limit):
    return min(max(int(limit or 25), 1), 200)

def _sf_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _sf_items(body, collection_key):
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        val = body.get(collection_key)
        if isinstance(val, list):
            return val
        if body.get('id') is not None:
            return [body]
    return []

def _sf_err(resp, body=None):
    if isinstance(body, dict):
        for key in ('message', 'error', 'errorMessage', 'detail'):
            if body.get(key):
                return str(body.get(key))[:1000]
    return (resp['body'] if resp is not None else 'request failed')[:1000]

async def _sf_request(method, path, base_url, params, json_body, timeout, verify_ssl):
    headers, err = _sf_auth(json_body=json_body is not None)
    if err:
        return (None, None, 401, err)
    root, _ = _sf_root(base_url)
    resp = await nexus_call(method, root + path, headers=headers, params=params, json=json_body)
    try:
        body = resp['json'] if resp['content'] else {}
    except Exception:
        body = {}
    if resp['status_code'] >= 400:
        return (resp, body, resp['status_code'], _sf_err(resp, body))
    return (resp, body, resp['status_code'], 'ok')

async def _sf_list(path, collection_key, base_url, limit, timeout, verify_ssl, extra_params=None):
    cap = _sf_cap(limit)
    records = []
    offset = 0
    page_size = min(cap, 100)
    status = 200
    msg = 'ok'
    while len(records) < cap:
        params = {'limit': min(page_size, cap - len(records)), 'offset': offset}
        if extra_params:
            params.update(extra_params)
        resp, body, status, msg = await _sf_request('GET', path, base_url, params, None, timeout, verify_ssl)
        if status >= 400:
            return (records, status, msg)
        chunk = _sf_items(body, collection_key)
        if not chunk:
            break
        for item in chunk:
            records.append(item)
            if len(records) >= cap:
                break
        if len(chunk) < min(page_size, cap - len(records) + len(chunk)):
            break
        offset += len(chunk)
        if offset > 10000:
            break
    return (records[:cap], status, msg)
