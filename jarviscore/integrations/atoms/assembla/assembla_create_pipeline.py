from typing import Any, Dict, List, Optional
_ASSEMBLA_V1_SUFFIX = '/v1'

async def assembla_create_pipeline(payload: Dict[str, Any], space_id: Optional[str]=None, space_tool_id: Optional[str]=None, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Create merge request in repo tool (POST .../merge_requests.json). Official: https://api-docs.assembla.cc/content/ref/merge_requests_create.html"""
    try:
        if not base_url:
            return _assembla_provision([], 400, 'base_url is required')
        api_root, root_err = _assembla_api_root(base_url)
        if root_err:
            return _assembla_provision([], 400, root_err)
        sid = _assembla_space_id(space_id)
        tool_id = _assembla_space_tool_id(space_tool_id)
        if not sid or not tool_id:
            return _assembla_provision([], 400, 'space_id and space_tool_id are required')
        headers, auth_err = _assembla_headers(json_body=True)
        if auth_err:
            return _assembla_provision([], 401, auth_err)
        url = _assembla_json_path(f'{api_root}/spaces/{sid}/space_tools/{tool_id}/merge_requests')
        resp = await nexus_call('POST', url, headers=headers, json=_assembla_wrap_namespace('merge_request', payload))
        status = resp['status_code']
        try:
            body = resp['json'] if resp['content'] else {}
        except Exception:
            body = {}
        if status >= 400:
            return _assembla_provision([], status, _assembla_err(resp))
        ids = _assembla_provision_ids(body)
        if not ids:
            location = resp['headers'].get('Location', '')
            if location:
                ids = [location.rstrip('/').split('/')[-1].replace('.json', '')]
        rec = body if isinstance(body, dict) else {}
        records = [rec] if rec else []
        return _assembla_provision(records, status, 'ok', ids)
    except Exception as e:
        return _assembla_provision([], 500, str(e))

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

def _assembla_wrap_namespace(namespace: str, payload: Dict[str, Any]):
    if isinstance(payload, dict) and isinstance(payload.get(namespace), dict):
        return payload
    return {namespace: payload or {}}

def _assembla_provision_id(body, keys=('id', 'number')):
    if not isinstance(body, dict):
        return []
    for key in keys:
        if body.get(key) not in (None, ''):
            return [body[key]]
    return []

def _assembla_provision(records, status, msg, provision_ids=None):
    recs = records if isinstance(records, list) else []
    ids = provision_ids if isinstance(provision_ids, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg, 'provision_ids': ids}

def _assembla_provision_ids(body, fallback_id=None, keys=('id', 'number')):
    ids = _assembla_provision_id(body, keys=keys)
    if ids:
        return [str(x) for x in ids]
    if fallback_id not in (None, ''):
        return [str(fallback_id)]
    return []

def _assembla_err(resp):
    return (resp['body'] if resp is not None else 'request failed')[:1000]

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
