from typing import Any, Dict, List, Optional

async def box_update_folder(folder_id: str, payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Update folder metadata (PUT /folders/{folder_id}). Official: https://developer.box.com/reference/put-folders-id/"""
    try:
        if not folder_id or not payload:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'folder_id and payload are required', 'provision_ids': []}
        headers, auth_err = _box_auth(json_body=True)
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err, 'provision_ids': []}
        api = _box_api_root(base_url)
        resp = await _box_put_json(f'{api}/folders/{folder_id}', headers, payload, timeout, verify_ssl)
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': resp['body'][:1000], 'provision_ids': []}
        data = resp['json'] if resp['body'] else {}
        return {'records': [data] if isinstance(data, dict) else [], 'data_count': 1 if isinstance(data, dict) else 0, 'status': resp['status_code'], 'message': 'ok', 'provision_ids': [folder_id]}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e), 'provision_ids': []}
BOX_API = 'https://api.box.com/2.0'
BOX_UPLOAD = 'https://upload.box.com/api/2.0'

def _box_api_root(base_url):
    root = (base_url or BOX_API).rstrip('/')
    if not root.endswith('/2.0'):
        if root.endswith('/2'):
            root = root + '.0'
        elif not root.endswith('/2.0'):
            root = root + '/2.0' if _host_is(root, 'box.com') else BOX_API
    return root

def _box_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

async def _box_put_json(url, headers, body, timeout, verify_ssl):
    return await nexus_call('PUT', url, headers=headers, json=body)

def _host_is(url, *domains):
    """True only if url's hostname equals or is a subdomain of one of domains."""
    from urllib.parse import urlparse
    u = str(url or '').strip()
    if '://' not in u:
        u = 'https://' + u
    try:
        host = (urlparse(u).hostname or '').lower()
    except Exception:
        return False
    return any((host == d or host.endswith('.' + d) for d in domains))
