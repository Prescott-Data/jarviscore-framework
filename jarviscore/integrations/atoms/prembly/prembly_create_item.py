from typing import Any, Dict, List, Optional

async def prembly_create_item(payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Create custom background-check package. Official: https://docs.prembly.com/reference/create-custom-package"""
    try:
        if not isinstance(payload, dict) or not payload:
            return _pm_provision({}, 400, 'payload is required')
        (root, err) = _pm_root(base_url)
        if err:
            return _pm_provision({}, 400, err)
        (resp, body, status, msg) = await _pm_request('post', root + '/api/v1/api/bgc/packages/', json_body=payload, timeout=timeout, verify_ssl=verify_ssl)
        if status >= 400:
            return _pm_provision(body if isinstance(body, dict) else {}, status, msg)
        data = body if isinstance(body, dict) else {}
        inner = data.get('data') if isinstance(data.get('data'), dict) else data
        return _pm_provision(inner if isinstance(inner, dict) else data, status, 'ok')
    except Exception as e:
        return _pm_provision({}, 500, str(e))

def _pm_root(base_url):
    root = (base_url or None or None or 'https://api.prembly.com').strip().rstrip('/')
    return (root, None)

def _pm_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _pm_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    ver = obj.get('verification') if isinstance(obj.get('verification'), dict) else {}
    pid = ver.get('verification_id') or ver.get('reference') or obj.get('id') or (obj.get('data') or {}).get('id') if isinstance(obj.get('data'), dict) else None or fallback_id
    ids = [pid] if pid not in (None, '') else []
    rec = obj if obj else {'id': pid} if ids else {}
    return {'records': [rec] if rec else [], 'data_count': 1 if rec else 0, 'status': status, 'message': msg, 'provision_ids': ids}

def _pm_err(resp, body=None):
    if isinstance(body, dict):
        err = body.get('message') or body.get('detail') or body.get('error')
        if err and (not isinstance(err, (list, dict))):
            return str(err)[:1000]
        if isinstance(err, list):
            return str(err)[:1000]
    return (resp['body'] if resp is not None else 'request failed')[:1000]

async def _pm_request(method, url, params=None, json_body=None, timeout=30, verify_ssl=True):
    (headers, err) = _pm_auth(json_body=json_body is not None)
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
        return (resp, body, resp['status_code'], _pm_err(resp, body))
    if isinstance(body, dict) and body.get('status') is False:
        return (resp, body, 400, _pm_err(resp, body))
    return (resp, body, resp['status_code'], 'ok')
