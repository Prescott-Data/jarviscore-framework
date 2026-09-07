from typing import Any, Dict, List, Optional
CIRCLECI_API = 'https://circleci.com/api/v2'

async def circleci_get_project(project_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Get Project via CircleCI API v2. Circle-Token auth. Official: https://circleci.com/docs/api/v2/operations/getProjectBySlug.md"""
    try:
        if not project_id:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'project_id (project slug, e.g. gh/org/repo) is required'}
        api = _circleci_api_root(base_url)
        headers, auth_err = _circleci_auth()
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        url, err = _circleci_project_path(api, project_id)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        resp = await _circleci_get(url, headers, None, timeout, verify_ssl)
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': resp['body'][:1000]}
        data = resp['json'] if resp['body'] else {}
        records = [data] if isinstance(data, dict) else []
        return {'records': records, 'data_count': len(records), 'status': resp['status_code'], 'message': 'ok'}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _circleci_api_root(base_url):
    root = (base_url or CIRCLECI_API).rstrip('/')
    if _host_is(root, 'circleci.com') and '/api/v2' not in root:
        root = root + '/api/v2' if not root.endswith('/api') else root + '/v2'
    return root

def _circleci_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

async def _circleci_get(url, headers, params, timeout, verify_ssl):
    return await nexus_call('GET', url, headers=headers, params=params)

def _circleci_project_path(api, project_slug):
    slug = (project_slug or '').strip().lstrip('/')
    if not slug:
        return (None, 'project_slug is required (e.g. gh/org/repo)')
    return (f'{api}/project/{slug}', None)

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
