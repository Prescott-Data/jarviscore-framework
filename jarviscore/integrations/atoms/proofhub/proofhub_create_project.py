from typing import Any, Dict, List, Optional

async def proofhub_create_project(payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Create a project. Official: https://github.com/ProofHub/api_v3/blob/master/README.md"""
    try:
        if not isinstance(payload, dict) or not payload:
            return _ph_provision({}, 400, 'payload is required')
        (root, err) = _ph_root(base_url)
        if err:
            return _ph_provision({}, 400, err)
        (resp, body, status, msg) = await _ph_request('post', root + '/projects', json_body=payload, timeout=timeout, verify_ssl=verify_ssl)
        if status >= 400:
            return _ph_provision(body if isinstance(body, dict) else {}, status, msg)
        return _ph_provision(body if isinstance(body, dict) else {}, status, 'ok')
    except Exception as e:
        return _ph_provision({}, 500, str(e))

def _ph_root(base_url):
    root = (base_url or None or None or None or '').strip().rstrip('/')
    if not root:
        return (None, 'base_url is required (https://company.proofhub.com/api/v3)')
    if '/api/v3' not in root:
        root = root + '/api/v3'
    return (root, None)

def _ph_auth(json_body=False):
    ua = None or None or 'jarviscoreIntegration (integration@jarviscore.io)'
    headers = {'User-Agent': str(ua).strip(), 'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _ph_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get('id') or fallback_id
    ids = [pid] if pid not in (None, '') else []
    rec = obj if obj else {'id': pid} if ids else {}
    return {'records': [rec] if rec else [], 'data_count': 1 if rec else 0, 'status': status, 'message': msg, 'provision_ids': ids}

def _ph_err(resp, body=None):
    if isinstance(body, dict):
        err = body.get('message') or body.get('error')
        if err:
            return str(err)[:1000]
    try:
        if resp is not None and resp['content']:
            data = resp['json']
            if isinstance(data, dict) and data.get('message'):
                return str(data.get('message'))[:1000]
    except Exception:
        pass
    return (resp['body'] if resp is not None else 'request failed')[:1000]

async def _ph_request(method, url, params=None, json_body=None, timeout=30, verify_ssl=True):
    (headers, err) = _ph_auth(json_body=json_body is not None)
    if err:
        return (None, None, 401, err)
    kwargs = {'headers': headers, 'timeout': timeout, 'verify': verify_ssl}
    if method == 'get':
        resp = await nexus_call('GET', url, params=params)
    elif method == 'post':
        resp = await nexus_call('POST', url, params=params, json=json_body)
    elif method == 'put':
        resp = await nexus_call('PUT', url, params=params, json=json_body)
    else:
        return (None, None, 400, f'unsupported method {method}')
    try:
        body = resp['json'] if resp['content'] else {}
    except Exception:
        body = {}
    if resp['status_code'] >= 400:
        return (resp, body, resp['status_code'], _ph_err(resp, body))
    return (resp, body, resp['status_code'], 'ok')
