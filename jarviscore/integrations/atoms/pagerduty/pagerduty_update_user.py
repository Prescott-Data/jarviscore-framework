from typing import Any, Dict, List, Optional

async def pagerduty_update_user(user_id: str, payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Update user via PUT. Official: https://developer.pagerduty.com/api-reference/operations/updateUser"""
    try:
        root, err = _pd_root(base_url)
        if err:
            return _pd_provision({}, 'user', 400, err)
        if not user_id:
            return _pd_provision({}, 'user', 400, 'user_id is required')
        if not isinstance(payload, dict) or not payload:
            return _pd_provision({}, 'user', 400, 'payload is required')
        body = _pd_wrap('user', payload)
        resp, status, err = await _pd_request('put', root + f'/users/{user_id}', json_body=body, timeout=timeout, verify_ssl=verify_ssl)
        if err:
            return _pd_provision({}, 'user', 401, err)
        try:
            data = resp['json'] if resp['content'] else {}
        except Exception:
            data = {}
        if status >= 400:
            return _pd_provision(data, 'user', status, _pd_err(resp))
        return _pd_provision(data, 'user', status, 'ok', fallback_id=user_id)
    except Exception as e:
        return _pd_provision({}, 'user', 500, str(e))

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

def _pd_provision(data, wrap_key, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    inner = obj.get(wrap_key) if isinstance(obj.get(wrap_key), dict) else obj
    if not isinstance(inner, dict):
        inner = {}
    pid = inner.get('id') or fallback_id
    ids = [pid] if pid not in (None, '') else []
    rec = inner if inner else {'id': pid} if ids else {}
    return {'records': [rec] if rec else [], 'data_count': 1 if rec else 0, 'status': status, 'message': msg, 'provision_ids': ids}

def _pd_wrap(key, payload):
    if not isinstance(payload, dict):
        return {key: payload if payload is not None else {}}
    if key in payload:
        return payload
    return {key: payload}

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
