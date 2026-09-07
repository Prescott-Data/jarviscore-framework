from typing import Any, Dict, List, Optional

async def wrike_create_project(name: str, limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """wrike REST: create project. Official: https://developers.wrike.com/api/v4/"""
    try:
        if not name:
            return _provision({}, 400, 'name is required')
        (root, err) = _root(base_url)
        if err:
            return _provision({}, 400, err)
        parent = (None or {}).get('parent_id') or (None or {}).get('folder_id') or (None or {}).get('space_id')
        if not parent:
            return _provision({}, 400, 'auth_info.parent_id (or folder_id/space_id) is required to create a project')
        (headers, aerr) = _auth()
        if aerr:
            return _provision({}, 401, aerr)
        resp = await nexus_call('POST', root + '/folders/' + str(parent) + '/folders', headers=headers, data={'title': name, 'project': '{}'})
        if resp['status_code'] >= 400:
            return _provision({}, resp['status_code'], _err(resp))
        data = resp['json'] if resp['content'] else {}
        rows = data.get('data') if isinstance(data, dict) else None
        obj = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else data if isinstance(data, dict) else {}
        return _provision(obj, resp['status_code'], 'ok')
    except Exception as e:
        return _provision({}, 500, str(e))

def _root(base_url):
    root = (base_url or None or 'https://www.wrike.com/api/v4').strip().rstrip('/')
    if not root:
        return (None, 'base_url is required')
    return (root, None)

def _auth():
    return ({'Accept': 'application/json'}, None)

def _provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get('id') or obj.get('ID') or fallback_id
    ids = [pid] if pid not in (None, '') else []
    rec = obj if obj else {'id': pid} if ids else {}
    return {'records': [rec] if rec else [], 'data_count': 1 if rec else 0, 'status': status, 'message': msg, 'provision_ids': ids}

def _err(resp):
    return (resp['body'] or f"HTTP {resp['status_code']}")[:1000]
