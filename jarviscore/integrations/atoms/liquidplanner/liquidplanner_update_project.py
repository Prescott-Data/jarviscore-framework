from typing import Any, Dict, List, Optional, Tuple, Union
LP_CLASSIC_API = 'https://app.liquidplanner.com/api/v1'

async def liquidplanner_update_project(workspace_id: str, project_id: str, payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Update a project via PUT with project wrapper. Official: https://developer.liquidplanner.com/docs/create-and-update-examples"""
    try:
        if not project_id:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'project_id is required', 'provision_ids': []}
        base, err = _lp_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err, 'provision_ids': []}
        ws, werr = _lp_workspace(workspace_id)
        if werr:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': werr, 'provision_ids': []}
        headers, aerr = _lp_headers(json_body=True)
        if aerr:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': aerr, 'provision_ids': []}
        body = _lp_write_body('project', payload or {})
        resp = await nexus_call('PUT', f'{base}/workspaces/{ws}/projects/{project_id}', headers=headers, json=body)
        try:
            data = resp['json'] if resp['body'] else {}
        except Exception:
            data = {}
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': _lp_error_message(data, resp['body']), 'provision_ids': []}
        result = _lp_provision(data, resp['status_code'])
        if not result['provision_ids']:
            result['provision_ids'] = [project_id]
            result['records'] = [{'id': project_id}]
            result['data_count'] = 1
        return result
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e), 'provision_ids': []}

def _lp_root(base_url):
    root = (base_url or LP_CLASSIC_API).rstrip('/')
    if 'liquidplanner.com' not in root:
        return (None, 'base_url must be https://app.liquidplanner.com/api/v1')
    return (root, None)

def _lp_workspace(workspace_id):
    ws = workspace_id or None
    if ws in (None, ''):
        return (None, 'workspace_id is required')
    return (str(ws), None)

def _lp_auth_header():
    prefix = 'Bearer '
    return (None, None)

def _lp_headers(json_body=False):
    auth, err = _lp_auth_header()
    if err:
        return (None, err)
    headers = {'Accept': 'application/json', 'Authorization': auth}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _lp_error_message(data, fallback=''):
    if isinstance(data, dict) and data.get('type') == 'Error':
        return str(data.get('message') or data.get('error') or fallback)[:1000]
    return (fallback or '')[:1000]

def _lp_write_body(resource, payload):
    if isinstance(payload, dict) and resource in payload:
        return payload
    return {resource: payload if isinstance(payload, dict) else {}}

def _lp_provision(data, status, message='ok'):
    obj = data if isinstance(data, dict) else {}
    obj_id = obj.get('id')
    records = [obj] if obj_id is not None else []
    ids = [obj_id] if obj_id is not None else []
    return {'records': records, 'data_count': len(records), 'status': status, 'message': message, 'provision_ids': ids}
