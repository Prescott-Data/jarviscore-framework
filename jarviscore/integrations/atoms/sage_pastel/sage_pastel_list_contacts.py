from typing import Any, Dict, List, Optional

async def sage_pastel_list_contacts(limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """List customers (contacts). Official: https://accounting.sageone.co.za/api/2.0.0/Help"""
    try:
        records, status, msg = await _pt_list('Customer', base_url, limit, timeout, verify_ssl)
        return _pt_dataset(records, status, msg)
    except Exception as e:
        return _pt_dataset([], 500, str(e))

def _pt_root(base_url):
    root = (base_url or None or None or None or 'https://accounting.sageone.co.za/api/2.0.0').strip().rstrip('/')
    if '/api/' in root and (not root.endswith('2.0.0')):
        if '2.0.0' not in root:
            root = root.split('/api/')[0] + '/api/2.0.0'
    elif 'accounting.sageone.co.za' in root and '/api/' not in root:
        root = root + '/api/2.0.0'
    return (root, None)

def _pt_query(extra=None):
    params = {}
    if extra:
        params.update(extra)
    return (params, None)

def _pt_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    import base64
    return (headers, None)

def _pt_cap(limit):
    return min(max(int(limit or 25), 1), 100)

def _pt_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _pt_items(body):
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ('Results', 'results', 'Items', 'items', 'Data', 'data'):
            val = body.get(key)
            if isinstance(val, list):
                return val
        if body.get('ID') is not None or body.get('Id') is not None:
            return [body]
    return []

def _pt_err(resp, body=None):
    if isinstance(body, dict):
        for key in ('Message', 'message', 'Error', 'error', 'ErrorMessage'):
            if body.get(key):
                return str(body.get(key))[:1000]
    return (resp['body'] if resp is not None else 'request failed')[:1000]

async def _pt_get(service, base_url, path_suffix, extra_params, timeout, verify_ssl):
    headers, err = _pt_auth()
    if err:
        return (None, None, 401, err)
    params, err = _pt_query(extra_params)
    if err:
        return (None, None, 401, err)
    root, _ = _pt_root(base_url)
    path = f'/{service}/Get'
    if path_suffix:
        path += f'/{path_suffix}'
    resp = await nexus_call('GET', root + path, headers=headers, params=params)
    try:
        body = resp['json'] if resp['content'] else {}
    except Exception:
        body = {}
    if resp['status_code'] >= 400:
        return (resp, body, resp['status_code'], _pt_err(resp, body))
    return (resp, body, resp['status_code'], 'ok')

async def _pt_list(service, base_url, limit, timeout, verify_ssl, extra_params=None):
    cap = _pt_cap(limit)
    records = []
    skip = 0
    page_size = min(cap, 100)
    status = 200
    msg = 'ok'
    while len(records) < cap:
        params = {'$skip': skip, '$top': min(page_size, cap - len(records)), '$orderby': 'ID'}
        if extra_params:
            params.update(extra_params)
        resp, body, status, msg = await _pt_get(service, base_url, None, params, timeout, verify_ssl)
        if status >= 400:
            return (records, status, msg)
        chunk = _pt_items(body)
        if not chunk:
            break
        for item in chunk:
            records.append(item)
            if len(records) >= cap:
                break
        if len(chunk) < min(page_size, cap - len(records) + len(chunk)):
            break
        skip += len(chunk)
        if skip > 5000:
            break
    return (records[:cap], status, msg)
