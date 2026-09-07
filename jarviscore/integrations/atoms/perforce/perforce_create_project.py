from typing import Any, Dict, List, Optional

async def perforce_create_project(payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Create Swarm project. Official: https://help.perforce.com/helix-core/helix-swarm/swarm/current/Content/Swarm/swarm-apidoc_endpoint_projects.html"""
    try:
        root, err = _pf_root(base_url)
        if err:
            return _pf_provision({}, 400, err)
        if not isinstance(payload, dict) or not payload:
            return _pf_provision({}, 400, 'payload is required')
        resp, data, status, err = await _pf_request('post', root + '/projects', json_body=payload, timeout=timeout, verify_ssl=verify_ssl)
        if err:
            return _pf_provision({}, 401, err)
        if status >= 400:
            return _pf_provision(data if isinstance(data, dict) else {}, status, _pf_err(resp))
        return _pf_provision(data if isinstance(data, dict) else {}, status, 'ok')
    except Exception as e:
        return _pf_provision({}, 500, str(e))

def _pf_root(base_url):
    root = (base_url or None or None or None or '').strip().rstrip('/')
    version = str(None or 'v11')
    if not root:
        return (None, 'base_url is required (https://my-swarm-host/api/v11)')
    if '/api/v' not in root:
        root = root + f'/api/{version}'
    return (root, None)

def _pf_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None, None)

def _pf_err(resp):
    try:
        data = resp['json']
        if isinstance(data, dict):
            msg = data.get('message') or data.get('error')
            if isinstance(msg, list):
                msg = '; '.join((str(x) for x in msg))
            if msg:
                return str(msg)[:1000]
    except Exception:
        pass
    return (resp['body'] or f'HTTP {resp['status_code']}')[:1000]

def _pf_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    inner = obj.get('project') if isinstance(obj.get('project'), dict) else obj
    pid = inner.get('id') or fallback_id
    ids = [pid] if pid not in (None, '') else []
    rec = inner if inner else {'id': pid} if ids else {}
    return {'records': [rec] if rec else [], 'data_count': 1 if rec else 0, 'status': status, 'message': msg, 'provision_ids': ids}

async def _pf_request(method, url, params=None, json_body=None, data=None, timeout=30, verify_ssl=True):
    headers, basic, err = _pf_auth(json_body=json_body is not None)
    if err:
        return (None, None, 401, err)
    kwargs = {'headers': headers, 'timeout': timeout, 'verify': verify_ssl}
    if basic is not None:
        kwargs['auth'] = basic
    if method == 'get':
        resp = await nexus_call('GET', url, params=params)
    elif method == 'post':
        if json_body is not None:
            resp = await nexus_call('POST', url, params=params, json=json_body)
        else:
            resp = await nexus_call('POST', url, params=params, data=data)
    elif method == 'patch':
        resp = await nexus_call('PATCH', url, params=params, json=json_body)
    else:
        return (None, None, 400, f'unsupported method {method}')
    try:
        body = resp['json'] if resp['content'] else {}
    except Exception:
        body = {}
    return (resp, body, resp['status_code'], None)
