from typing import Any, Dict, List, Optional

async def box_list_folders(timeout: int=30, verify_ssl: bool=True, folder_id: str='0', limit: int=25, base_url: str=None) -> dict:
    """List subfolders in a folder (GET /folders/{folder_id}/items, type=folder). Official: https://developer.box.com/reference/get-folders-id-items/"""
    try:
        headers, auth_err = _box_auth()
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        api = _box_api_root(base_url)
        url = f'{api}/folders/{folder_id}/items'
        records, status, message = await _box_paginate_typed_items(url, headers, limit, timeout, verify_ssl, 'folder')
        return {'records': records, 'data_count': len(records), 'status': status, 'message': message}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}
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

async def _box_get(url, headers, params, timeout, verify_ssl):
    return await nexus_call('GET', url, headers=headers, params=params)

async def _box_paginate_typed_items(url, headers, limit, timeout, verify_ssl, item_type, extra=None):
    records = []
    offset = 0
    status = 0
    extra = extra or {}
    page_size = min(max(limit, 1), 1000)
    while len(records) < limit:
        params = {'limit': min(page_size, max(limit * 2, 25)), 'offset': offset}
        params.update(extra)
        resp = await _box_get(url, headers, params, timeout, verify_ssl)
        status = resp['status_code']
        if status >= 400:
            return (records, status, resp['body'][:1000])
        data = resp['json'] if resp['body'] else {}
        batch = data.get('entries') or []
        for item in batch:
            if isinstance(item, dict) and item.get('type') == item_type:
                records.append(item)
                if len(records) >= limit:
                    break
        total = data.get('total_count')
        offset += len(batch)
        if not batch or (total is not None and offset >= total):
            break
        if offset > 100000:
            break
    return (records[:limit], status, 'ok')

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
