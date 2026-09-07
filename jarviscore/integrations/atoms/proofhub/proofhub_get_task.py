from typing import Any, Dict, List, Optional

async def proofhub_get_task(task_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Get a task by ID. Official: https://github.com/ProofHub/api_v3/blob/master/README.md"""
    try:
        if not task_id:
            return _ph_dataset([], 400, 'task_id is required')
        project_id, todolist_id, _ = _ph_ids()
        if not project_id or not todolist_id:
            return _ph_dataset([], 400, 'auth_info.project_id and auth_info.todolist_id are required')
        root, err = _ph_root(base_url)
        if err:
            return _ph_dataset([], 400, err)
        url = root + f'/projects/{project_id}/todolists/{todolist_id}/tasks/{task_id}'
        resp, body, status, msg = await _ph_request('get', url, timeout=timeout, verify_ssl=verify_ssl)
        if status >= 400:
            return _ph_dataset([], status, msg)
        rows = _ph_rows(body)
        return _ph_dataset(rows if rows else [body] if isinstance(body, dict) else [], status, msg)
    except Exception as e:
        return _ph_dataset([], 500, str(e))

def _ph_root(base_url):
    root = (base_url or None or None or None or '').strip().rstrip('/')
    if not root:
        return (None, 'base_url is required (https://company.proofhub.com/api/v3)')
    if '/api/v3' not in root:
        root = root + '/api/v3'
    return (root, None)

def _ph_auth(json_body=False):
    ua = None or None or 'jarviscoreIntegration (integration@jarviscore.io)'
    headers = {'User-Agent': str(ua).strip(), 'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _ph_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _ph_err(resp, body=None):
    if isinstance(body, dict):
        err = body.get('message') or body.get('error')
        if err:
            return str(err)[:1000]
    try:
        if resp is not None and resp['content']:
            data = resp['json']
            if isinstance(data, dict) and data.get('message'):
                return str(data.get('message'))[:1000]
    except Exception:
        pass
    return (resp['body'] if resp is not None else 'request failed')[:1000]

def _ph_rows(body):
    if isinstance(body, list):
        return [x for x in body if isinstance(x, dict)]
    if isinstance(body, dict):
        for key in ('todos', 'results', 'data', 'items'):
            val = body.get(key)
            if isinstance(val, list):
                return [x for x in val if isinstance(x, dict)]
        return [body]
    return []

async def _ph_request(method, url, params=None, json_body=None, timeout=30, verify_ssl=True):
    headers, err = _ph_auth(json_body=json_body is not None)
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
        return (resp, body, resp['status_code'], _ph_err(resp, body))
    return (resp, body, resp['status_code'], 'ok')

def _ph_ids(payload=None):
    payload = payload if isinstance(payload, dict) else {}
    project_id = payload.get('project_id') or None
    todolist_id = payload.get('todolist_id') or payload.get('list_id') or None or None
    task_id = payload.get('task_id') or None
    return (project_id, todolist_id, task_id)
