from typing import Any, Dict, List, Optional

async def rocket_chat_create_conversation(payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Create a public channel. Official: https://developer.rocket.chat/apidocs/authentication-api"""
    try:
        if not isinstance(payload, dict) or not payload.get('name'):
            return _rc_provision({}, 400, 'payload.name is required')
        (root, err) = _rc_root(base_url)
        if err:
            return _rc_provision({}, 400, err)
        (resp, body, status, msg) = await _rc_request('post', root + '/channels.create', json_body=payload, timeout=timeout, verify_ssl=verify_ssl)
        if status >= 400:
            return _rc_provision(body if isinstance(body, dict) else {}, status, msg)
        channel = body.get('channel') if isinstance(body.get('channel'), dict) else body
        return _rc_provision(channel if isinstance(channel, dict) else {}, status, 'ok')
    except Exception as e:
        return _rc_provision({}, 500, str(e))

def _rc_root(base_url):
    root = (base_url or None or None or '').strip().rstrip('/')
    if not root:
        return (None, 'base_url is required')
    if not root.endswith('/api/v1'):
        if '/api/v1' in root:
            root = root.split('/api/v1')[0] + '/api/v1'
        else:
            root = root + '/api/v1'
    return (root, None)

def _rc_auth():
    return ({'Accept': 'application/json'}, None)

def _rc_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get('_id') or obj.get('id') or fallback_id
    ids = [pid] if pid not in (None, '') else []
    rec = obj if obj else {'_id': pid} if ids else {}
    return {'records': [rec] if rec else [], 'data_count': 1 if rec else 0, 'status': status, 'message': msg, 'provision_ids': ids}

def _rc_err(resp, body=None):
    if isinstance(body, dict):
        err = body.get('error') or body.get('message')
        if err:
            return str(err)[:1000]
    return (resp['body'] if resp is not None else 'request failed')[:1000]

def _rc_ok(body):
    if isinstance(body, dict) and body.get('success') is False:
        return False
    if isinstance(body, dict) and body.get('status') == 'error':
        return False
    return True

async def _rc_request(method, url, params=None, json_body=None, timeout=30, verify_ssl=True):
    (headers, err) = _rc_auth()
    if err:
        return (None, None, 401, err)
    if json_body is not None:
        headers = dict(headers)
        headers['Content-Type'] = 'application/json'
    kwargs = {'headers': headers, 'timeout': timeout, 'verify': verify_ssl}
    if method == 'get':
        resp = await nexus_call('GET', url, params=params)
    elif method == 'post':
        resp = await nexus_call('POST', url, params=params, json=json_body)
    else:
        return (None, None, 400, f'unsupported method {method}')
    try:
        body = resp['json'] if resp['content'] else {}
    except Exception:
        body = {}
    if resp['status_code'] >= 400 or not _rc_ok(body):
        status = resp['status_code'] if resp['status_code'] >= 400 else 400
        return (resp, body, status, _rc_err(resp, body))
    return (resp, body, resp['status_code'], 'ok')
