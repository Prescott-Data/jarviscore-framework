from typing import Any, Dict, List, Optional

async def beanstalk_create_project(payload: Dict[str, Any], account: Optional[str]=None, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Create repository. POST /api/repositories.json. Official: https://api.beanstalkapp.com/repository"""
    try:
        if not payload:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'payload is required'}
        api_root, err = _beanstalk_api_root(base_url, account)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        headers, basic, auth_err = _beanstalk_auth(json_body=True)
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err, 'provision_ids': []}
        body = payload if 'repository' in payload else {'repository': payload}
        resp = await _beanstalk_post(api_root, '/repositories.json', headers, basic, body, None, timeout, verify_ssl)
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': resp['body'][:1000]}
        data = resp['json'] if resp['body'] else {}
        repo = data.get('repository') if isinstance(data, dict) else data
        prov = [repo.get('id')] if isinstance(repo, dict) and repo.get('id') is not None else []
        return {'records': [repo] if repo else [], 'data_count': 1 if repo else 0, 'status': resp['status_code'], 'message': 'ok', 'provision_ids': prov}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _beanstalk_api_root(base_url, account=None):
    root = (base_url or '').rstrip('/')
    if not root and account:
        root = f'https://{account}.beanstalkapp.com'
    if not root:
        return (None, 'base_url or account is required (https://{account}.beanstalkapp.com)')
    if not root.endswith('/api'):
        if _host_is(root, 'beanstalkapp.com') and (not root.endswith('/api')):
            root = root + '/api'
    return (root, None)

def _beanstalk_auth(json_body=False):
    headers = {'Accept': 'application/json', 'User-Agent': 'jarviscore/1.0'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (None, None, 'auth_info requires username and password')

async def _beanstalk_post(api_root, path, headers, basic, body, params, timeout, verify_ssl):
    return await nexus_call('POST', f'{api_root}{path}', headers=headers, json=body, params=params)

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
