from typing import Any, Dict, List, Optional

async def posthog_create_report(payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Create saved insight. Official: https://posthog.com/docs/api/product-analytics-2"""
    try:
        if not isinstance(payload, dict) or not payload:
            return _pg_provision({}, 400, 'payload is required')
        project_id = _pg_project_id()
        if not project_id:
            return _pg_provision({}, 400, 'auth_info.project_id is required')
        host = _pg_app_host(base_url)
        (resp, body, status, msg) = await _pg_request('post', host + f'/api/projects/{project_id}/insights/', json_body=payload, timeout=timeout, verify_ssl=verify_ssl)
        if status >= 400:
            return _pg_provision(body if isinstance(body, dict) else {}, status, msg)
        data = body if isinstance(body, dict) else {}
        return _pg_provision(data, status, 'ok')
    except Exception as e:
        return _pg_provision({}, 500, str(e))

def _pg_app_host(base_url):
    host = (base_url or None or None or 'https://us.posthog.com').strip().rstrip('/')
    if host.endswith('/api'):
        host = host[:-4]
    return host.rstrip('/')

def _pg_project_id():
    return None or None

def _pg_private_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _pg_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get('id') or obj.get('uuid') or obj.get('short_id') or fallback_id
    ids = [pid] if pid not in (None, '') else []
    rec = obj if obj else {'id': pid} if ids else {}
    return {'records': [rec] if rec else [], 'data_count': 1 if rec else 0, 'status': status, 'message': msg, 'provision_ids': ids}

def _pg_err(resp, body=None):
    if isinstance(body, dict):
        err = body.get('detail') or body.get('error') or body.get('message')
        if err:
            return str(err)[:1000]
    return (resp['body'] if resp is not None else 'request failed')[:1000]

async def _pg_request(method, url, params=None, json_body=None, timeout=30, verify_ssl=True, private=True):
    if private:
        (headers, err) = _pg_private_auth(json_body=json_body is not None)
    else:
        headers = {'Accept': 'application/json'}
        if json_body is not None:
            headers['Content-Type'] = 'application/json'
        err = None
    if err:
        return (None, None, 401, err)
    kwargs = {'headers': headers, 'timeout': timeout, 'verify': verify_ssl}
    if method == 'get':
        resp = await nexus_call('GET', url, params=params)
    elif method == 'post':
        resp = await nexus_call('POST', url, params=params, json=json_body)
    elif method == 'patch':
        resp = await nexus_call('PATCH', url, params=params, json=json_body)
    else:
        return (None, None, 400, f'unsupported method {method}')
    try:
        body = resp['json'] if resp['content'] else {}
    except Exception:
        body = {}
    if resp['status_code'] >= 400:
        return (resp, body, resp['status_code'], _pg_err(resp, body))
    return (resp, body, resp['status_code'], 'ok')
