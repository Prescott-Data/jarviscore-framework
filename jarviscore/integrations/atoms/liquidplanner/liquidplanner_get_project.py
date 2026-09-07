from typing import Any, Dict, List, Optional, Tuple, Union
LP_CLASSIC_API = 'https://app.liquidplanner.com/api/v1'

async def liquidplanner_get_project(workspace_id: str, project_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Get a project by ID. Official: https://developer.liquidplanner.com/docs/requests-and-responses"""
    try:
        if not project_id:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'project_id is required'}
        (base, err) = _lp_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        (ws, werr) = _lp_workspace(workspace_id)
        if werr:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': werr}
        (headers, aerr) = _lp_headers()
        if aerr:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': aerr}
        resp = await nexus_call('GET', f'{base}/workspaces/{ws}/projects/{project_id}', headers=headers)
        try:
            data = resp['json'] if resp['body'] else {}
        except Exception:
            data = {}
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': _lp_error_message(data, resp['body'])}
        records = _lp_records(data)
        return {'records': records, 'data_count': len(records), 'status': resp['status_code'], 'message': 'ok'}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

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
    (auth, err) = _lp_auth_header()
    if err:
        return (None, err)
    headers = {'Accept': 'application/json', 'Authorization': auth}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _lp_records(data):
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        if data.get('type') == 'Error':
            return []
        if data.get('id') is not None:
            return [data]
    return []

def _lp_error_message(data, fallback=''):
    if isinstance(data, dict) and data.get('type') == 'Error':
        return str(data.get('message') or data.get('error') or fallback)[:1000]
    return (fallback or '')[:1000]
