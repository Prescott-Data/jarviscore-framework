from typing import Any, Dict, List, Optional
HEIGHT_API = 'https://api.height.app'

async def height_list_projects(limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """List Height lists (catalog project maps to Height list). Official: https://height.app/api-docs"""
    try:
        api, err = _height_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        headers, auth_err = _height_auth()
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        records, status, message = await _height_paginate(f'{api}/lists', headers, limit, timeout, verify_ssl)
        return {'records': records, 'data_count': len(records), 'status': status, 'message': message}
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

async def _height_get(url, headers, params, timeout, verify_ssl):
    return await nexus_call('GET', url, headers=headers, params=params)

def _height_items(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ('list', 'data', 'items', 'results'):
            batch = data.get(key)
            if isinstance(batch, list):
                return batch
    return []

async def _height_paginate(url, headers, limit, timeout, verify_ssl, extra_params=None):
    params = dict(extra_params or {})
    cap = min(max(int(limit or 25), 1), 100)
    params.setdefault('limit', cap)
    resp = await _height_get(url, headers, params, timeout, verify_ssl)
    status = resp['status_code']
    if status >= 400:
        return ([], status, resp['body'][:1000])
    batch = _height_items(resp['json'] if resp['body'] else {})
    records = [item for item in batch if isinstance(item, dict)][:cap]
    return (records, status, 'ok')
