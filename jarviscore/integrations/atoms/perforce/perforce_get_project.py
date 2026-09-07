from typing import Any, Dict, List, Optional

async def perforce_get_project(project_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Get Swarm project by id. Official: https://help.perforce.com/helix-core/helix-swarm/swarm/current/Content/Swarm/swarm-apidoc_endpoint_projects.html"""
    try:
        root, err = _pf_root(base_url)
        if err:
            return _pf_dataset([], 400, err)
        if not project_id:
            return _pf_dataset([], 400, 'project_id is required')
        params = {}
        resp, data, status, err = await _pf_request('get', root + f'/projects/{project_id}', params=params, timeout=timeout, verify_ssl=verify_ssl)
        if err:
            return _pf_dataset([], 401, err)
        if status >= 400:
            return _pf_dataset([], status, _pf_err(resp))
        return _pf_dataset(_pf_projects(data), status, 'ok')
    except Exception as e:
        return _pf_dataset([], 500, str(e))

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

def _pf_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _pf_projects(data):
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        items = data.get('projects')
        if isinstance(items, list):
            return [x for x in items if isinstance(x, dict)]
        proj = data.get('project')
        if isinstance(proj, dict):
            return [proj]
    return []

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
