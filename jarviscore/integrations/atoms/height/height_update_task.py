from typing import Any, Dict, List, Optional
HEIGHT_API = 'https://api.height.app'

async def height_update_task(task_id: str, payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Update a Height task. Official: https://height.app/api-docs"""
    try:
        if not task_id:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'task_id is required'}
        if not payload:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'payload is required'}
        api, err = _height_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        headers, auth_err = _height_auth(json_body=True)
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        resp = await _height_patch(f'{api}/tasks/{task_id}', headers, payload, timeout, verify_ssl)
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': resp['body'][:1000]}
        records = _height_single(resp['json'] if resp['body'] else {})
        return {'records': records, 'data_count': len(records), 'status': resp['status_code'], 'message': 'ok'}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _height_api_root(base_url):
    root = (base_url or HEIGHT_API).rstrip('/')
    if 'height.app' not in root:
        return (None, 'base_url must be https://api.height.app')
    return (root, None)

def _height_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

async def _height_patch(url, headers, body, timeout, verify_ssl):
    return await nexus_call('PATCH', url, headers=headers, json=body)

def _height_single(data):
    if isinstance(data, dict):
        if isinstance(data.get('data'), dict):
            return [data['data']]
        if data.get('id') is not None:
            return [data]
    return []
