from typing import Any, Dict, List, Optional
NIFTY_API = 'https://openapi.niftypm.com/api/v1.0'

async def nifty_get_project(project_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Get project by ID. Official: https://developers.niftypm.com/operation/operation-projectapicontroller_getprojectbyid"""
    try:
        if not project_id:
            return _nf_dataset([], 400, 'project_id is required')
        (root, err) = _nf_root(base_url)
        if err:
            return _nf_dataset([], 400, err)
        (headers, aerr) = _nf_auth()
        if aerr:
            return _nf_dataset([], 401, aerr)
        resp = await nexus_call('GET', f'{root}/projects/{project_id}', headers=headers)
        if resp['status_code'] >= 400:
            return _nf_dataset([], resp['status_code'], _nf_error(resp))
        try:
            data = resp['json']
        except Exception:
            return _nf_dataset([], resp['status_code'], resp['body'][:1000])
        records = [data] if isinstance(data, dict) else []
        return _nf_dataset(records, resp['status_code'], 'ok')
    except Exception as e:
        return _nf_dataset([], 500, str(e))

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

def _nf_dataset(records, status, msg):
    return {'records': records, 'data_count': len(records), 'status': status, 'message': msg}

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
