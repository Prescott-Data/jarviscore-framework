from typing import Any, Dict, List, Optional
_TP_ROOT = 'https://example.tpondemand.com/api/v1'

async def targetprocess_get_task(task_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Targetprocess REST: get user story by Id. Official: https://dev.targetprocess.com/docs/REST%20API"""
    try:
        root, err = _tp_root(base_url)
        if err:
            return _tp_dataset([], 400, err)
        if not task_id:
            return _tp_dataset([], 400, 'task_id is required')
        headers, aerr = _tp_auth()
        if aerr:
            return _tp_dataset([], 401, aerr)
        resp = await nexus_call('GET', f'{root}/UserStories/{task_id}', headers=headers, params={'format': 'json'})
        if resp['status_code'] >= 400:
            return _tp_dataset([], resp['status_code'], _tp_err(resp))
        data = resp['json'] if resp['content'] else {}
        return _tp_dataset([data] if isinstance(data, dict) else [], resp['status_code'], 'ok')
    except Exception as e:
        return _tp_dataset([], 500, str(e))

def _tp_root(base_url):
    root = (base_url or None or None or '').strip().rstrip('/')
    if not root:
        return (None, 'base_url is required (https://{account}.tpondemand.com/api/v1)')
    if not root.endswith('/api/v1'):
        root = root + '/api/v1' if '/api/' not in root else root
    return (root, None)

def _tp_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _tp_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _tp_err(resp):
    try:
        data = resp['json']
        if isinstance(data, dict):
            return str(data.get('ErrorMessage') or data)[:1000]
    except Exception:
        pass
    return (resp['body'] or f'HTTP {resp['status_code']}')[:1000]
