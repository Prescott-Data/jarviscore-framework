from typing import Any, Dict, List, Optional

async def sage_business_cloud_accounting_list_payments(limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """List contact payments. Official: https://developer.sage.com/accounting/reference/"""
    try:
        (records, status, msg) = await _sage_list_collection('/contact_payments', base_url, limit, timeout, verify_ssl)
        return _sage_dataset(records, status, msg)
    except Exception as e:
        return _sage_dataset([], 500, str(e))

def _sage_root(base_url):
    root = (base_url or None or None or None or 'https://api.accounting.sage.com/v3.1').strip().rstrip('/')
    if not root.endswith('/v3.1'):
        if '/v3.1/' in root:
            root = root.split('/v3.1/')[0] + '/v3.1'
        elif not root.endswith('v3.1'):
            root = root + '/v3.1'
    return (root, None)

def _sage_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    business = None or None
    if business not in (None, ''):
        headers['X-Business'] = str(business)
    return (headers, None)

def _sage_cap(limit):
    return min(max(int(limit or 25), 1), 200)

def _sage_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _sage_items(body, wrapper=None):
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        items = body.get('$items')
        if isinstance(items, list):
            return items
        if wrapper:
            inner = body.get(wrapper)
            if isinstance(inner, dict):
                return [inner]
        if body.get('id'):
            return [body]
    return []

def _sage_err(resp, body=None):
    if isinstance(body, dict):
        for key in ('$message', 'message', 'error', 'error_description'):
            if body.get(key):
                return str(body.get(key))[:1000]
        errors = body.get('$errors') or body.get('errors')
        if isinstance(errors, list) and errors:
            first = errors[0]
            if isinstance(first, dict):
                return str(first.get('message') or first.get('$message') or first)[:1000]
            return str(first)[:1000]
    return (resp['body'] if resp is not None else 'request failed')[:1000]

def _sage_next_url(root, body):
    if not isinstance(body, dict):
        return None
    nxt = body.get('$next')
    if not nxt:
        return None
    nxt = str(nxt)
    if nxt.startswith('http'):
        return nxt
    host = root.split('/v3.1')[0]
    if nxt.startswith('/v3.1'):
        return host + nxt
    if nxt.startswith('/'):
        return root + nxt
    return root + '/' + nxt

async def _sage_get(path, base_url, params, timeout, verify_ssl):
    (headers, err) = _sage_auth()
    if err:
        return (None, None, 401, err)
    (root, _) = _sage_root(base_url)
    resp = await nexus_call('GET', root + path, headers=headers, params=params)
    try:
        body = resp['json'] if resp['content'] else {}
    except Exception:
        body = {}
    if resp['status_code'] >= 400:
        return (resp, body, resp['status_code'], _sage_err(resp, body))
    return (resp, body, resp['status_code'], 'ok')

async def _sage_list_collection(path, base_url, limit, timeout, verify_ssl, extra_params=None):
    cap = _sage_cap(limit)
    records = []
    params = {'items_per_page': min(cap, 200), 'page': 1}
    if extra_params:
        params.update(extra_params)
    (root, _) = _sage_root(base_url)
    status = 200
    msg = 'ok'
    pages = 0
    next_url = None
    while pages < 50 and len(records) < cap:
        pages += 1
        if next_url:
            (headers, err) = _sage_auth()
            if err:
                return (records, 401, err)
            resp = await nexus_call('GET', next_url, headers=headers)
            try:
                body = resp['json'] if resp['content'] else {}
            except Exception:
                body = {}
            status = resp['status_code']
            if status >= 400:
                return (records, status, _sage_err(resp, body))
        else:
            (resp, body, status, msg) = await _sage_get(path, base_url, params, timeout, verify_ssl)
            if status >= 400:
                return (records, status, msg)
        for item in _sage_items(body):
            records.append(item)
            if len(records) >= cap:
                break
        next_url = _sage_next_url(root, body) if len(records) < cap else None
        if not next_url:
            break
    return (records[:cap], status, msg)
