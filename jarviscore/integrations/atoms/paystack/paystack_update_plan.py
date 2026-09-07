from typing import Any, Dict, List, Optional

async def paystack_update_plan(plan_id: str, payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Update plan by id or plan code via PUT. Official: https://paystack.com/docs/api/plan/#update-plan"""
    try:
        (root, err) = _ps_root(base_url)
        if err:
            return _ps_provision({}, 400, err)
        if not plan_id:
            return _ps_provision({}, 400, 'plan_id is required')
        if not isinstance(payload, dict) or not payload:
            return _ps_provision({}, 400, 'payload is required')
        (resp, data, status, err) = await _ps_request('put', root + f'/plan/{plan_id}', json_body=payload, timeout=timeout, verify_ssl=verify_ssl)
        if err:
            return _ps_provision({}, 401, err)
        if not _ps_ok(resp, data):
            return _ps_provision(data, status, _ps_err(resp))
        return _ps_provision(data, status, 'ok', fallback_id=plan_id)
    except Exception as e:
        return _ps_provision({}, 500, str(e))

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
    return (resp['body'] or f"HTTP {resp['status_code']}")[:1000]

def _ps_ok(resp, data):
    if resp['status_code'] >= 400:
        return False
    return not (isinstance(data, dict) and data.get('status') is False)

def _ps_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    inner = obj.get('data') if isinstance(obj.get('data'), dict) else obj
    if not isinstance(inner, dict):
        inner = obj
    pid = inner.get('reference') or inner.get('customer_code') or inner.get('plan_code') or inner.get('id') or fallback_id
    ids = [pid] if pid not in (None, '') else []
    rec = inner if inner else {'id': pid} if ids else {}
    return {'records': [rec] if rec else [], 'data_count': 1 if rec else 0, 'status': status, 'message': msg, 'provision_ids': ids}

async def _ps_request(method, url, params=None, json_body=None, timeout=30, verify_ssl=True):
    (headers, err) = _ps_auth(json_body=json_body is not None)
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
