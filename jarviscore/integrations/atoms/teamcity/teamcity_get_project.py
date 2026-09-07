from typing import Any, Dict, List, Optional

async def teamcity_get_project(project_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """TeamCity REST: get project. Official: https://www.jetbrains.com/help/teamcity/rest/teamcity-rest.html"""
    try:
        (root, err) = _tc_root(base_url)
        if err:
            return _tc_dataset([], 400, err)
        if not project_id:
            return _tc_dataset([], 400, 'project_id is required')
        (headers, aerr) = _tc_auth()
        if aerr:
            return _tc_dataset([], 401, aerr)
        resp = await nexus_call('GET', f'{root}/projects/id:{project_id}', headers=headers)
        if resp['status_code'] >= 400:
            return _tc_dataset([], resp['status_code'], _tc_err(resp))
        data = resp['json'] if resp['content'] else {}
        return _tc_dataset([data] if isinstance(data, dict) else [], resp['status_code'], 'ok')
    except Exception as e:
        return _tc_dataset([], 500, str(e))

def _tc_root(base_url):
    root = (base_url or None or None or '').strip().rstrip('/')
    if not root:
        return (None, 'base_url is required (https://teamcity.example.com)')
    if not root.endswith('/app/rest'):
        root = root + '/app/rest' if '/app/' not in root else root
    return (root, None)

def _tc_auth():
    return ({'Accept': 'application/json'}, None)

def _tc_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _tc_err(resp):
    return (resp['body'] or f"HTTP {resp['status_code']}")[:1000]
