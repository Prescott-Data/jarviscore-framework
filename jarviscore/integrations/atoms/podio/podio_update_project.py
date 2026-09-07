from typing import Any, Dict, List, Optional

async def podio_update_project(project_id: str, payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Update app configuration. Official: https://developers.podio.com/doc/applications/update-app-22342"""
    try:
        if not project_id:
            return _po_provision({}, 400, 'project_id is required')
        if not isinstance(payload, dict) or not payload:
            return _po_provision({}, 400, 'payload is required')
        root, err = _po_root(base_url)
        if err:
            return _po_provision({}, 400, err)
        resp, body, status, msg = await _po_request('put', root + '/app/' + str(project_id).strip(), json_body=payload, timeout=timeout, verify_ssl=verify_ssl)
        if status >= 400:
            return _po_provision(body if isinstance(body, dict) else {}, status, msg)
        data = body if isinstance(body, dict) else {}
        return _po_provision(data, status, 'ok', fallback_id=project_id)
    except Exception as e:
        return _po_provision({}, 500, str(e))

def _po_root(base_url):
    root = (base_url or None or None or 'https://api.podio.com').strip().rstrip('/')
    return (root, None)

def _po_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _po_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get('app_id') or obj.get('task_id') or obj.get('item_id') or obj.get('id') or fallback_id
    ids = [pid] if pid not in (None, '') else []
    rec = obj if obj else {'id': pid} if ids else {}
    return {'records': [rec] if rec else [], 'data_count': 1 if rec else 0, 'status': status, 'message': msg, 'provision_ids': ids}

def _po_err(resp, body=None):
    if isinstance(body, dict):
        err = body.get('error_description') or body.get('error')
        if err:
            return str(err)[:1000]
    return (resp['body'] if resp is not None else 'request failed')[:1000]

async def _po_request(method, url, params=None, json_body=None, timeout=30, verify_ssl=True):
    headers, err = _po_auth(json_body=json_body is not None)
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
        return (resp, body, resp['status_code'], _po_err(resp, body))
    return (resp, body, resp['status_code'], 'ok')
