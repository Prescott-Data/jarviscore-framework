from typing import Any, Dict, List, Optional

async def asana_update_project(project_id: str, payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Update project via PUT /projects/{project_gid}. Official: https://developers.asana.com/reference/updateproject"""
    try:
        if not project_id:
            return _asana_provision([], 400, 'project_id is required')
        api_root, err = _asana_api_root(base_url)
        if err:
            return _asana_provision([], 400, err)
        headers, err = _asana_headers(json_body=True)
        if err:
            return _asana_provision([], 401, err)
        resp = await nexus_call('PUT', f'{api_root}/projects/{project_id}', headers=headers, json=_asana_wrap_data(payload))
        status = resp['status_code']
        if status >= 400:
            return _asana_provision([], status, _asana_err(resp))
        try:
            body = resp['json'] if resp['content'] else {}
        except Exception:
            return _asana_provision([], status, 'invalid JSON response')
        obj = body.get('data') if isinstance(body, dict) else None
        records: List[Dict[str, Any]] = [obj] if isinstance(obj, dict) else []
        return _asana_provision(records, status, 'ok', _asana_provision_ids(body, project_id))
    except Exception as e:
        return _asana_provision([], 500, str(e))

def _asana_api_root(base_url):
    root = str(base_url or '').strip().rstrip('/')
    if root.endswith('/api/1.0'):
        return (root, None)
    if root.endswith('/api'):
        return (root + '/1.0', None)
    if root == 'https://app.asana.com' or (_host_is(root, 'app.asana.com') and '/' not in root.split('://', 1)[-1]):
        return (root + '/api/1.0', None)
    return (None, 'base_url must be https://app.asana.com/api/1.0')

def _asana_headers(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _asana_wrap_data(payload):
    if isinstance(payload, dict) and isinstance(payload.get('data'), dict):
        return payload
    return {'data': payload or {}}

def _asana_provision(records, status, msg, provision_ids=None):
    recs = records if isinstance(records, list) else []
    ids = provision_ids if isinstance(provision_ids, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg, 'provision_ids': ids}

def _asana_provision_ids(body, fallback_id=None):
    if isinstance(body, dict) and isinstance(body.get('data'), dict):
        gid = body['data'].get('gid')
        if gid not in (None, ''):
            return [str(gid)]
    if fallback_id not in (None, ''):
        return [str(fallback_id)]
    return []

def _asana_err(resp):
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
