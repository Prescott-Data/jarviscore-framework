from typing import Any, Dict, List, Optional

async def sage_pastel_create_payment(payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Create customer receipt. Official: https://accounting.sageone.co.za/api/2.0.0/Help"""
    try:
        if not isinstance(payload, dict) or not payload:
            return _pt_provision({}, 400, 'payload is required')
        extra = {}
        resp, body, status, msg = await _pt_save('CustomerReceipt', base_url, payload, timeout, verify_ssl, extra)
        if status >= 400:
            return _pt_provision(body if isinstance(body, dict) else {}, status, msg)
        return _pt_provision(body if isinstance(body, dict) else {}, status, 'ok')
    except Exception as e:
        return _pt_provision({}, 500, str(e))

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

def _pt_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get('ID') or obj.get('Id') or obj.get('id') or fallback_id
    ids = [pid] if pid not in (None, '') else []
    rec = obj if obj else {'ID': pid} if ids else {}
    return {'records': [rec] if rec else [], 'data_count': 1 if rec else 0, 'status': status, 'message': msg, 'provision_ids': ids}

def _pt_err(resp, body=None):
    if isinstance(body, dict):
        for key in ('Message', 'message', 'Error', 'error', 'ErrorMessage'):
            if body.get(key):
                return str(body.get(key))[:1000]
    return (resp['body'] if resp is not None else 'request failed')[:1000]

async def _pt_save(service, base_url, payload, timeout, verify_ssl, extra_params=None):
    headers, err = _pt_auth(json_body=True)
    if err:
        return (None, None, 401, err)
    params, err = _pt_query(extra_params)
    if err:
        return (None, None, 401, err)
    root, _ = _pt_root(base_url)
    resp = await nexus_call('POST', root + f'/{service}/Save', headers=headers, params=params, json=payload)
    try:
        body = resp['json'] if resp['content'] else {}
    except Exception:
        body = {}
    if resp['status_code'] >= 400:
        return (resp, body, resp['status_code'], _pt_err(resp, body))
    return (resp, body, resp['status_code'], 'ok')
