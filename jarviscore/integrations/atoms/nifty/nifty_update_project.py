from typing import Any, Dict, List, Optional
NIFTY_API = 'https://openapi.niftypm.com/api/v1.0'

async def nifty_update_project(project_id: str, payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Update project via multipart/form-data. Official: https://developers.niftypm.com/operation/operation-projectapicontroller_updateproject"""
    try:
        if not project_id:
            return _nf_provision([], 400, 'project_id is required', [])
        (root, err) = _nf_root(base_url)
        if err:
            return _nf_provision([], 400, err, [])
        (headers, aerr) = _nf_auth()
        if aerr:
            return _nf_provision([], 400, aerr, [])
        form = _nf_form_payload(payload if isinstance(payload, dict) else {})
        resp = await nexus_call('PUT', f'{root}/projects/{project_id}', headers=headers, data=form)
        try:
            data = resp['json'] if resp['content'] else {}
        except Exception:
            data = {}
        if resp['status_code'] >= 400:
            return _nf_provision([], resp['status_code'], _nf_error(resp), [])
        pid = _nf_provision_id(data if isinstance(data, dict) else {}, fallback=project_id)
        rec = data if isinstance(data, dict) and data else {'id': pid}
        return _nf_provision([rec], resp['status_code'], 'ok', [pid])
    except Exception as e:
        return _nf_provision([], 500, str(e), [])

def _nf_root(base_url):
    root = (base_url or NIFTY_API).rstrip('/')
    if not _host_is(root, 'niftypm.com'):
        return (None, 'base_url must be https://openapi.niftypm.com/api/v1.0')
    if not root.endswith('/api/v1.0'):
        if '/' not in root.split('://', 1)[-1]:
            root = root + '/api/v1.0'
    return (root, None)

def _nf_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _nf_error(resp):
    try:
        data = resp['json']
        if isinstance(data, dict):
            msg = data.get('message') or data.get('error') or data.get('detail')
            if msg:
                return str(msg)[:1000]
    except Exception:
        pass
    return (resp['body'] or f"HTTP {resp['status_code']}")[:1000]

def _nf_form_payload(payload):
    body = payload if isinstance(payload, dict) else {}
    form = {}
    for (key, val) in body.items():
        if val in (None, ''):
            continue
        if isinstance(val, bool):
            form[key] = 'true' if val else 'false'
        elif isinstance(val, (list, dict)):
            import json
            form[key] = json.dumps(val)
        else:
            form[key] = str(val)
    return form

def _nf_provision_id(data, fallback=None):
    if isinstance(data, dict):
        for key in ('id', 'task_id', 'project_id'):
            if data.get(key) not in (None, ''):
                return data.get(key)
    return fallback

def _nf_provision(records, status, msg, provision_ids):
    return {'records': records, 'data_count': len(records), 'status': status, 'message': msg, 'provision_ids': provision_ids or []}

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
