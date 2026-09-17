from typing import Any, Dict, List, Optional

async def pivotal_tracker_get_task(task_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Get story by ID (catalog task). Official: https://www.pivotaltracker.com/help/api/rest/v5"""
    try:
        if not task_id:
            return _pt_dataset([], 400, 'task_id is required')
        project_id = _pt_project_id()
        if not project_id:
            return _pt_dataset([], 400, 'auth_info.project_id is required for story get')
        (root, err) = _pt_root(base_url)
        if err:
            return _pt_dataset([], 400, err)
        path = '/projects/' + str(project_id).strip() + '/stories/' + str(task_id).strip()
        (resp, body, status, msg) = await _pt_request('get', root + path, timeout=timeout, verify_ssl=verify_ssl)
        if status >= 400:
            return _pt_dataset([], status, msg)
        return _pt_dataset(_pt_items(body), status, msg)
    except Exception as e:
        return _pt_dataset([], 500, str(e))

def _pt_root(base_url):
    root = (base_url or None or None or None or 'https://www.pivotaltracker.com/services/v5').strip().rstrip('/')
    if '/services/v' not in root:
        root = root + '/services/v5'
    return (root, None)

def _pt_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _pt_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _pt_project_id(payload=None):
    pid = None or None
    if isinstance(payload, dict):
        pid = payload.get('project_id') or payload.get('projectId') or pid
    return pid

def _pt_err(resp, body=None):
    if isinstance(body, dict):
        err = body.get('error') or body.get('message')
        if err:
            return str(err)[:1000]
    return (resp['body'] if resp is not None else 'request failed')[:1000]

def _pt_items(data):
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        inner = data.get('data')
        if isinstance(inner, list):
            return [x for x in inner if isinstance(x, dict)]
        if inner is not None:
            return [inner] if isinstance(inner, dict) else []
        return [data]
    return []

async def _pt_request(method, url, params=None, json_body=None, timeout=30, verify_ssl=True):
    (headers, err) = _pt_auth(json_body=json_body is not None)
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
        return (resp, body, resp['status_code'], _pt_err(resp, body))
    return (resp, body, resp['status_code'], 'ok')
