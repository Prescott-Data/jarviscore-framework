from typing import Any, Dict, List, Optional
NIMBLE_V1 = 'https://api.nimble.com/api/v1'
NIMBLE_V2 = 'https://api.nimble.com/api/v2'

async def nimble_get_contact(contact_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Get contact by id. Official: https://www.nimble.com/developers/docs/"""
    try:
        if not contact_id:
            return _nb_dataset([], 400, 'contact_id is required')
        (root, err) = _nb_v1_root(base_url)
        if err:
            return _nb_dataset([], 400, err)
        (headers, aerr) = _nb_auth()
        if aerr:
            return _nb_dataset([], 401, aerr)
        (records, status, msg) = await _nb_get_one(f'{root}/contact/{contact_id}', headers, timeout, verify_ssl)
        return _nb_dataset(records, status, msg)
    except Exception as e:
        return _nb_dataset([], 500, str(e))

def _nb_v1_root(base_url):
    root = (base_url or NIMBLE_V1).rstrip('/')
    if not _host_is(root, 'nimble.com'):
        return (None, 'base_url must be https://api.nimble.com/api/v1 or https://app.nimble.com/api/v1')
    if '/' not in root.split('://', 1)[-1]:
        root = root + '/api/v1'
    elif '/api/v2' in root:
        root = root.replace('/api/v2', '/api/v1')
    elif not root.endswith('/api/v1'):
        if '/api/' not in root:
            root = root + '/api/v1'
    return (root, None)

def _nb_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _nb_error(resp):
    try:
        data = resp['json']
        if isinstance(data, dict):
            msg = data.get('message') or data.get('error') or data.get('status')
            if msg:
                return str(msg)[:1000]
    except Exception:
        pass
    return (resp['body'] or f"HTTP {resp['status_code']}")[:1000]

def _nb_dataset(records, status, msg):
    return {'records': records, 'data_count': len(records), 'status': status, 'message': msg}

def _nb_resources(data):
    if isinstance(data, dict):
        res = data.get('resources')
        if isinstance(res, list):
            if res and isinstance(res[0], dict):
                return [x for x in res if isinstance(x, dict)]
            return [{'id': x} for x in res if x not in (None, '')]
        if data.get('id') or data.get('deal_id'):
            return [data]
    return []

async def _nb_get_one(url, headers, timeout, verify_ssl):
    resp = await nexus_call('GET', url, headers=headers)
    status = resp['status_code']
    if status >= 400:
        return ([], status, _nb_error(resp))
    try:
        data = resp['json']
    except Exception:
        return ([], status, resp['body'][:1000])
    recs = _nb_resources(data)
    if not recs and isinstance(data, dict) and (data.get('deal_id') or data.get('id')):
        recs = [data]
    return (recs, status, 'ok')

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
