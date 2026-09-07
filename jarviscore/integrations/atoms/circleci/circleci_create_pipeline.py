from typing import Any, Dict, List, Optional
CIRCLECI_API = 'https://circleci.com/api/v2'

async def circleci_create_pipeline(timeout: int=30, verify_ssl: bool=True, payload: Optional[Dict[str, Any]]=None, base_url: str=None) -> dict:
    """Create Pipeline via CircleCI API v2. Circle-Token auth. Official: https://circleci.com/docs/api/v2/operations/triggerPipeline.md"""
    try:
        api = _circleci_api_root(base_url)
        headers, auth_err = _circleci_auth(json_body=True)
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        payload = payload or {}
        slug = payload.get('project_slug') or payload.get('project_id')
        if not slug:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'payload.project_slug or payload.project_id is required'}
        url, err = _circleci_project_path(api, slug)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        body = _circleci_pipeline_body(payload)
        resp = await _circleci_post(f'{url}/pipeline', headers, body, timeout, verify_ssl)
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': resp['body'][:1000]}
        data = resp['json'] if resp['body'] else {}
        prov = _circleci_provision_id(data)
        records = [data] if isinstance(data, dict) else []
        return {'records': records, 'data_count': len(records), 'status': resp['status_code'], 'message': 'ok', 'provision_ids': prov}
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

async def _circleci_post(url, headers, body, timeout, verify_ssl):
    return await nexus_call('POST', url, headers=headers, json=body)

def _circleci_project_path(api, project_slug):
    slug = (project_slug or '').strip().lstrip('/')
    if not slug:
        return (None, 'project_slug is required (e.g. gh/org/repo)')
    return (f'{api}/project/{slug}', None)

def _circleci_provision_id(data):
    if not isinstance(data, dict):
        return []
    for key in ('id', 'number', 'pipeline_number', 'pipeline_id'):
        if data.get(key) not in (None, ''):
            return [data.get(key)]
    return []

def _circleci_pipeline_body(payload, branch=None, parameters=None):
    body = dict(payload) if isinstance(payload, dict) else {}
    for key in ('project_slug', 'project_id'):
        body.pop(key, None)
    if branch is not None:
        body['branch'] = branch
    if parameters is not None:
        body['parameters'] = parameters
    return body

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
