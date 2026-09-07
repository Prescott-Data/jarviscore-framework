from typing import Any, Dict, List, Optional
HEIGHT_API = 'https://api.height.app'

async def height_create_task(payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Create a Height task. Official: https://height.app/api-docs"""
    try:
        if not payload:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'payload is required'}
        api, err = _height_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        headers, auth_err = _height_auth(json_body=True)
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err, 'provision_ids': []}
        resp = await _height_post(f'{api}/tasks', headers, payload, timeout, verify_ssl)
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': resp['body'][:1000]}
        data = resp['json'] if resp['body'] else {}
        records = _height_single(data)
        return {'records': records, 'data_count': len(records), 'status': resp['status_code'], 'message': 'ok', 'provision_ids': _height_provision_id(data)}
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

async def _height_post(url, headers, body, timeout, verify_ssl):
    return await nexus_call('POST', url, headers=headers, json=body)

def _height_single(data):
    if isinstance(data, dict):
        if isinstance(data.get('data'), dict):
            return [data['data']]
        if data.get('id') is not None:
            return [data]
    return []

def _height_provision_id(data):
    recs = _height_single(data)
    if recs and recs[0].get('id') not in (None, ''):
        return [recs[0]['id']]
    return []
