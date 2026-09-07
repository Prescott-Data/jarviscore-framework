from typing import Any, Dict, List, Optional

async def square_get_customer(customer_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Square API v2: get customer. Official: https://developer.squareup.com/reference/square/customers-api/retrieve-customer"""
    try:
        if not customer_id:
            return _sq_dataset([], 400, 'customer_id is required')
        root, _ = _sq_root(base_url)
        path = '/customers' if resource != 'payment' else '/payments'
        if resource == 'customer':
            path = '/customers'
        elif resource == 'order':
            path = '/orders'
        elif resource == 'payment':
            path = '/payments'
        _, data, status, msg = await _sq_request('get', root + path + '/{customer_id}'.format(**locals()), timeout=timeout, verify_ssl=verify_ssl)
        if status >= 400:
            return _sq_dataset([], status, msg)
        obj = data.get('customer') if isinstance(data, dict) else {}
        return _sq_dataset([obj] if isinstance(obj, dict) else [], status, 'ok')
    except Exception as e:
        return _sq_dataset([], 500, str(e))

def _sq_root(base_url):
    root = (base_url or None or None or 'https://connect.squareup.com').strip().rstrip('/')
    return (root + '/v2', None)

def _sq_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _sq_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _sq_err(resp, body=None):
    if isinstance(body, dict):
        errs = body.get('errors')
        if isinstance(errs, list) and errs:
            return str(errs[0])[:1000]
    return (resp['body'] if resp is not None else 'request failed')[:1000]

async def _sq_request(method, url, params=None, json_body=None, timeout=30, verify_ssl=True):
    headers, err = _sq_auth(json_body=json_body is not None)
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
    if resp['status_code'] >= 400:
        return (resp, data, resp['status_code'], _sq_err(resp, data))
    if isinstance(data, dict) and data.get('errors'):
        return (resp, data, 400, _sq_err(resp, data))
    return (resp, data, resp['status_code'], 'ok')
