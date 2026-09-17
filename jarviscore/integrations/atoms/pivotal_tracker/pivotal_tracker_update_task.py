from typing import Any, Dict, List, Optional

async def pivotal_tracker_update_task(task_id: str, payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Update story (catalog task). Official: https://www.pivotaltracker.com/help/api/rest/v5"""
    try:
        if not task_id:
            return _pt_provision({}, 400, 'task_id is required')
        if not isinstance(payload, dict) or not payload:
            return _pt_provision({}, 400, 'payload is required')
        project_id = _pt_project_id(payload)
        if not project_id:
            return _pt_provision({}, 400, 'auth_info.project_id is required for story update')
        (root, err) = _pt_root(base_url)
        if err:
            return _pt_provision({}, 400, err)
        body_payload = dict(payload)
        body_payload.pop('project_id', None)
        body_payload.pop('projectId', None)
        path = '/projects/' + str(project_id).strip() + '/stories/' + str(task_id).strip()
        (resp, body, status, msg) = await _pt_request('put', root + path, json_body=body_payload, timeout=timeout, verify_ssl=verify_ssl)
        if status >= 400:
            return _pt_provision(body if isinstance(body, dict) else {}, status, msg)
        data = body if isinstance(body, dict) else {}
        return _pt_provision(data, status, 'ok', fallback_id=task_id)
    except Exception as e:
        return _pt_provision({}, 500, str(e))

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

def _pt_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get('id') or fallback_id
    ids = [pid] if pid not in (None, '') else []
    rec = obj if obj else {'id': pid} if ids else {}
    return {'records': [rec] if rec else [], 'data_count': 1 if rec else 0, 'status': status, 'message': msg, 'provision_ids': ids}

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
