from typing import Any, Dict, List, Optional
_ASSEMBLA_V1_SUFFIX = '/v1'

async def assembla_list_pipelines(space_id: Optional[str]=None, space_tool_id: Optional[str]=None, limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """List merge requests in a repo tool (GET ./merge_requests.json). Mapped from pipeline catalog op. Official: https://api-docs.assembla.cc"""
    try:
        if not base_url:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'base_url is required'}
        (api_root, root_err) = _assembla_api_root(base_url)
        if root_err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': root_err}
        sid = _assembla_space_id(space_id)
        tool_id = _assembla_space_tool_id(space_tool_id)
        if not sid or not tool_id:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'space_id and space_tool_id are required (repo tool with merge requests)'}
        (headers, auth_err) = _assembla_headers()
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        url = _assembla_json_path(f'{api_root}/spaces/{sid}/space_tools/{tool_id}/merge_requests')
        (records, status, message) = await _assembla_paginate_page(url, headers, limit, timeout, verify_ssl, per_page_default=10)
        if message != 'ok':
            return {'records': records, 'data_count': len(records), 'status': status, 'message': message}
        return {'records': records, 'data_count': len(records), 'status': status, 'message': 'ok'}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _assembla_api_root(base_url: str):
    root = base_url.rstrip('/')
    if root.endswith('/v1'):
        return (root, None)
    if root.endswith('/api'):
        return (root + '/v1', None)
    if root == 'https://api.assembla.com' or (_host_is(root, 'api.assembla.com') and '/' not in root.split('://', 1)[-1]):
        return (root + '/v1', None)
    return (None, 'base_url must be https://api.assembla.com/v1')

def _assembla_headers(json_body: bool=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (None, 'auth_info requires username and password')

def _assembla_json_path(path: str) -> str:
    return path if path.endswith('.json') else f'{path}.json'

def _assembla_space_id(space_id=None):
    return space_id or None or None or None

def _assembla_space_tool_id(space_tool_id=None):
    return space_tool_id or None or None or None

async def _assembla_paginate_page(url, headers, limit, timeout, verify_ssl, extra_params=None, per_page_default=25):
    records: List[Dict[str, Any]] = []
    page = 1
    status = 0
    extra_params = dict(extra_params or {})
    per_page = min(max(limit, 1), 100)
    while len(records) < limit:
        params = dict(extra_params)
        params['page'] = page
        params['per_page'] = min(per_page, limit - len(records)) if 'per_page' not in params else params['per_page']
        resp = await nexus_call('GET', url, headers=headers, params=params)
        status = resp['status_code']
        if status >= 400:
            return (records, status, resp['body'][:1000])
        try:
            data = resp['json']
        except Exception:
            return (records, status, 'Unexpected response format')
        batch = data if isinstance(data, list) else []
        if not batch:
            break
        for item in batch:
            if isinstance(item, dict):
                records.append(item)
                if len(records) >= limit:
                    break
        if len(batch) < params.get('per_page', per_page):
            break
        page += 1
        if page > 200:
            break
    return (records[:limit], status, 'ok')

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
