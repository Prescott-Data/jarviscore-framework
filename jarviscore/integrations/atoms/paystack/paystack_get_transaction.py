from typing import Any, Dict, List, Optional

async def paystack_get_transaction(transaction_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Fetch transaction by numeric id. Official: https://paystack.com/docs/api/transaction/#fetch-transaction"""
    try:
        root, err = _ps_root(base_url)
        if err:
            return _ps_dataset([], 400, err)
        if not transaction_id:
            return _ps_dataset([], 400, 'transaction_id is required')
        resp, data, status, err = await _ps_request('get', root + f'/transaction/{transaction_id}', timeout=timeout, verify_ssl=verify_ssl)
        if err:
            return _ps_dataset([], 401, err)
        if not _ps_ok(resp, data):
            return _ps_dataset([], status, _ps_err(resp))
        return _ps_dataset(_ps_items(data), status, 'ok')
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
