from typing import Any, Dict, List, Optional

async def sage_pastel_get_contact(contact_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Get customer by ID. Official: https://accounting.sageone.co.za/api/2.0.0/Help"""
    try:
        if not contact_id:
            return _pt_dataset([], 400, 'contact_id is required')
        (resp, body, status, msg) = await _pt_get('Customer', base_url, str(contact_id), None, timeout, verify_ssl)
        if status >= 400:
            return _pt_dataset([], status, msg)
        rec = body if isinstance(body, dict) else {}
        return _pt_dataset([rec] if rec else [], status, msg)
    except Exception as e:
        return _pt_dataset([], 500, str(e))

def _pt_root(base_url):
    root = (base_url or None or None or None or 'https://accounting.sageone.co.za/api/2.0.0').strip().rstrip('/')
    if '/api/' in root and (not root.endswith('2.0.0')):
        if '2.0.0' not in root:
            root = root.split('/api/')[0] + '/api/2.0.0'
    elif 'accounting.sageone.co.za' in root and '/api/' not in root:
        root = root + '/api/2.0.0'
    return (root, None)

def _pt_query(extra=None):
    params = {}
    if extra:
        params.update(extra)
    return (params, None)

def _pt_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    import base64
    return (headers, None)

def _pt_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _pt_err(resp, body=None):
    if isinstance(body, dict):
        for key in ('Message', 'message', 'Error', 'error', 'ErrorMessage'):
            if body.get(key):
                return str(body.get(key))[:1000]
    return (resp['body'] if resp is not None else 'request failed')[:1000]

async def _pt_get(service, base_url, path_suffix, extra_params, timeout, verify_ssl):
    (headers, err) = _pt_auth()
    if err:
        return (None, None, 401, err)
    (params, err) = _pt_query(extra_params)
    if err:
        return (None, None, 401, err)
    (root, _) = _pt_root(base_url)
    path = f'/{service}/Get'
    if path_suffix:
        path += f'/{path_suffix}'
    resp = await nexus_call('GET', root + path, headers=headers, params=params)
    try:
        body = resp['json'] if resp['content'] else {}
    except Exception:
        body = {}
    if resp['status_code'] >= 400:
        return (resp, body, resp['status_code'], _pt_err(resp, body))
    return (resp, body, resp['status_code'], 'ok')
