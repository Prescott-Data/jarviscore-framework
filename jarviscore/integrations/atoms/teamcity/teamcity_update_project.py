from typing import Any, Dict, List, Optional

async def teamcity_update_project(project_id: str, name: str='', timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """TeamCity REST: update project. Official: https://www.jetbrains.com/help/teamcity/rest/teamcity-rest.html"""
    try:
        (root, err) = _tc_root(base_url)
        if err:
            return _tc_provision({}, 400, err)
        if not project_id:
            return _tc_provision({}, 400, 'project_id is required')
        (headers, aerr) = _tc_auth()
        if aerr:
            return _tc_provision({}, 401, aerr)
        headers['Content-Type'] = 'text/plain'
        resp = await nexus_call('PUT', f'{root}/projects/id:{project_id}/name', headers=headers, data=name or project_id)
        if resp['status_code'] >= 400:
            return _tc_provision({}, resp['status_code'], _tc_err(resp))
        return _tc_provision({'id': project_id, 'name': name}, resp['status_code'], 'ok', fallback_id=project_id)
    except Exception as e:
        return _tc_provision({}, 500, str(e))

def _tc_root(base_url):
    root = (base_url or None or None or '').strip().rstrip('/')
    if not root:
        return (None, 'base_url is required (https://teamcity.example.com)')
    if not root.endswith('/app/rest'):
        root = root + '/app/rest' if '/app/' not in root else root
    return (root, None)

def _tc_auth():
    return ({'Accept': 'application/json'}, None)

def _tc_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get('id') or fallback_id
    ids = [pid] if pid not in (None, '') else []
    rec = obj if obj else {'id': pid} if ids else {}
    return {'records': [rec] if rec else [], 'data_count': 1 if rec else 0, 'status': status, 'message': msg, 'provision_ids': ids}

def _tc_err(resp):
    return (resp['body'] or f"HTTP {resp['status_code']}")[:1000]
