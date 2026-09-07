from typing import Any, Dict, List, Optional

async def beanstalk_get_pipeline(pipeline_id: str, repository_id: str, account: Optional[str]=None, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Get server environment. GET /api/{repository_id}/server_environments/{id}.json. Official: https://api.beanstalkapp.com/server_environment"""
    try:
        if not pipeline_id or not repository_id:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'pipeline_id and repository_id are required'}
        api_root, err = _beanstalk_api_root(base_url, account)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        headers, basic, auth_err = _beanstalk_auth()
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        resp = await _beanstalk_get(api_root, f'/{repository_id}/server_environments/{pipeline_id}.json', headers, basic, None, timeout, verify_ssl)
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': resp['body'][:1000]}
        data = resp['json'] if resp['body'] else {}
        env = data.get('server_environment') if isinstance(data, dict) else data
        return {'records': [env] if env else [], 'data_count': 1 if env else 0, 'status': resp['status_code'], 'message': 'ok'}
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

async def _beanstalk_get(api_root, path, headers, basic, params, timeout, verify_ssl):
    return await nexus_call('GET', f'{api_root}{path}', headers=headers, params=params)

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
