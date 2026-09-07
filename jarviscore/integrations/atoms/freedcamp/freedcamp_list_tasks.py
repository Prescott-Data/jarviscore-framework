from typing import Any, Dict, List, Optional
_FC_API_ROOT = 'https://freedcamp.com/api/v1'

async def freedcamp_list_tasks(project_id: Optional[str]=None, limit: int=200, offset: int=0, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """List tasks (optional project_id, limit/offset max 200). Official: https://freedcamp.com/help_/tutorials/wiki/wiki_public/view/DFaab#/tasks"""
    try:
        api, err = _fc_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        headers, auth, auth_err = _fc_auth_params()
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        params = dict(auth)
        params.update({'limit': min(max(int(limit or 200), 1), 200), 'offset': max(int(offset or 0), 0)})
        if project_id:
            params['project_id'] = project_id
        resp = await nexus_call('GET', f'{api}/tasks', headers=headers, params=params)
        status = resp['status_code']
        if status >= 400:
            return {'records': [], 'data_count': 0, 'status': status, 'message': resp['body'][:1000]}
        body = resp['json'] if resp['body'] else {}
        records = body.get('tasks') if isinstance(body, dict) and isinstance(body.get('tasks'), list) else _fc_records(body)
        records = [x for x in records if isinstance(x, dict)]
        return {'records': records, 'data_count': len(records), 'status': status, 'message': 'ok'}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _fc_api_root(base_url: str):
    root = (base_url or _FC_API_ROOT).rstrip('/')
    if not root.endswith('/api/v1'):
        if _host_is(root, 'freedcamp.com'):
            root = root if root.endswith('/api/v1') else f'{root.rstrip('/')}/api/v1'
        else:
            return (None, 'base_url must be Freedcamp API root (https://freedcamp.com/api/v1)')
    return (root, None)

def _fc_auth_params() -> tuple:
    headers: Dict[str, str] = {'Accept': 'application/json'}
    params: Dict[str, Any] = {}
    return (headers, params, None)

def _fc_records(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, dict):
        inner = data.get('data')
        if isinstance(inner, list):
            return [x for x in inner if isinstance(x, dict)]
        if isinstance(inner, dict):
            return [inner]
        if any((k in data for k in ('id', 'project_id', 'task_id', 'title'))):
            return [data]
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    return []

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
