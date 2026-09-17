from typing import Any, Dict, List, Optional

async def pipedrive_get_organization(organization_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Get organization by ID. Official: https://developers.pipedrive.com/docs/api/v1/Organizations"""
    try:
        (records, status, msg) = await _pi_get('/organizations', base_url, organization_id, timeout, verify_ssl)
        return _pi_dataset(records, status, msg)
    except Exception as e:
        return _pi_dataset([], 500, str(e))

def _pi_root(base_url):
    root = (base_url or None or None or None or '').strip().rstrip('/')
    if not root:
        return (None, 'base_url is required (https://company.pipedrive.com)')
    if root.startswith('http') and _host_is(root, 'pipedrive.com') and ('/api/' not in root):
        root = root + '/api/v2'
    elif '/api/v1' in root:
        root = root.replace('/api/v1', '/api/v2')
    elif '/api/v' not in root:
        root = root + '/api/v2'
    return (root, None)

def _pi_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _pi_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _pi_err(resp, body=None):
    if isinstance(body, dict):
        err = body.get('error') or body.get('error_info')
        if err:
            return str(err)[:1000]
    try:
        if resp is not None:
            data = resp['json']
            if isinstance(data, dict):
                err = data.get('error') or data.get('error_info')
                if err:
                    return str(err)[:1000]
    except Exception:
        pass
    return (resp['body'] if resp is not None else 'request failed')[:1000]

def _pi_items(data):
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        return [data]
    return []

async def _pi_request(method, url, params=None, json_body=None, timeout=30, verify_ssl=True):
    (headers, err) = _pi_auth(json_body=json_body is not None)
    if err:
        return (None, None, 401, err)
    kwargs = {'headers': headers, 'timeout': timeout, 'verify': verify_ssl}
    if method == 'get':
        resp = await nexus_call('GET', url, params=params)
    elif method == 'post':
        resp = await nexus_call('POST', url, params=params, json=json_body)
    elif method == 'patch':
        resp = await nexus_call('PATCH', url, params=params, json=json_body)
    else:
        return (None, None, 400, f'unsupported method {method}')
    try:
        body = resp['json'] if resp['content'] else {}
    except Exception:
        body = {}
    if resp['status_code'] >= 400:
        return (resp, body, resp['status_code'], _pi_err(resp, body))
    if isinstance(body, dict) and body.get('success') is False:
        return (resp, body, 400, _pi_err(resp, body))
    return (resp, body, resp['status_code'], 'ok')

async def _pi_get(path, base_url, obj_id, timeout, verify_ssl):
    if not obj_id:
        return ([], 400, 'id is required')
    (root, err) = _pi_root(base_url)
    if err:
        return ([], 400, err)
    (resp, body, status, msg) = await _pi_request('get', root + path + '/' + str(obj_id).strip(), timeout=timeout, verify_ssl=verify_ssl)
    if status >= 400:
        return ([], status, msg)
    return (_pi_items(body.get('data') if isinstance(body, dict) else None), status, msg)

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
