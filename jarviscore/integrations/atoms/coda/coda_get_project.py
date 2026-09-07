from typing import Any, Dict, List, Optional
CODA_API = 'https://coda.io/apis/v1'

async def coda_get_project(project_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Get a Coda doc (catalog project) by doc id. Bearer API token in Authorization header. Official: https://coda.io/apis/v1"""
    try:
        if not project_id:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'project_id is required'}
        api = _coda_api_root(base_url)
        headers, auth_err = _coda_auth()
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        resp = await _coda_get(f'{api}/docs/{project_id}', headers, None, timeout, verify_ssl)
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': resp['body'][:1000]}
        data = resp['json'] if resp['body'] else {}
        return {'records': [data] if isinstance(data, dict) else [], 'data_count': 1 if isinstance(data, dict) else 0, 'status': resp['status_code'], 'message': 'ok'}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _coda_api_root(base_url):
    root = (base_url or CODA_API).rstrip('/')
    if _host_is(root, 'coda.io') and '/apis/v1' not in root:
        if root.endswith('/apis'):
            root = root + '/v1'
        else:
            root = root + '/apis/v1'
    return root

def _coda_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (None, 'auth_info requires api_key or access_token (Bearer)')

async def _coda_get(url, headers, params, timeout, verify_ssl):
    return await nexus_call('GET', url, headers=headers, params=params)

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
