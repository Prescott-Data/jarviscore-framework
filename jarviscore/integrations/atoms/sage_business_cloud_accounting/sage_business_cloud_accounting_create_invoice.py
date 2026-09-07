from typing import Any, Dict, List, Optional

async def sage_business_cloud_accounting_create_invoice(payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Create sales invoice. Official: https://developer.sage.com/accounting/reference/"""
    try:
        if not isinstance(payload, dict) or not payload:
            return _sage_provision({}, 400, 'payload is required', 'sales_invoice')
        body_payload = _sage_wrap(payload, 'sales_invoice')
        (resp, body, status, msg) = await _sage_write('POST', '/sales_invoices', base_url, body_payload, timeout, verify_ssl)
        if status >= 400:
            return _sage_provision(body if isinstance(body, dict) else {}, status, msg, 'sales_invoice')
        return _sage_provision(body if isinstance(body, dict) else {}, status, 'ok', 'sales_invoice')
    except Exception as e:
        return _sage_provision({}, 500, str(e), 'sales_invoice')

def _sage_root(base_url):
    root = (base_url or None or None or None or 'https://api.accounting.sage.com/v3.1').strip().rstrip('/')
    if not root.endswith('/v3.1'):
        if '/v3.1/' in root:
            root = root.split('/v3.1/')[0] + '/v3.1'
        elif not root.endswith('v3.1'):
            root = root + '/v3.1'
    return (root, None)

def _sage_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    business = None or None
    if business not in (None, ''):
        headers['X-Business'] = str(business)
    return (headers, None)

def _sage_provision(data, status, msg, wrapper, fallback_id=None):
    obj = _sage_entity_obj(data, wrapper) or (data if isinstance(data, dict) else {})
    pid = (obj.get('id') if isinstance(obj, dict) else None) or fallback_id
    ids = [pid] if pid not in (None, '') else []
    rec = obj if obj else {'id': pid} if ids else {}
    return {'records': [rec] if rec else [], 'data_count': 1 if rec else 0, 'status': status, 'message': msg, 'provision_ids': ids}

def _sage_entity_obj(body, wrapper):
    if not isinstance(body, dict):
        return {}
    inner = body.get(wrapper)
    if isinstance(inner, dict):
        return inner
    if body.get('id'):
        return body
    return {}

def _sage_err(resp, body=None):
    if isinstance(body, dict):
        for key in ('$message', 'message', 'error', 'error_description'):
            if body.get(key):
                return str(body.get(key))[:1000]
        errors = body.get('$errors') or body.get('errors')
        if isinstance(errors, list) and errors:
            first = errors[0]
            if isinstance(first, dict):
                return str(first.get('message') or first.get('$message') or first)[:1000]
            return str(first)[:1000]
    return (resp['body'] if resp is not None else 'request failed')[:1000]

async def _sage_write(method, path, base_url, json_body, timeout, verify_ssl):
    (headers, err) = _sage_auth(json_body=True)
    if err:
        return (None, None, 401, err)
    (root, _) = _sage_root(base_url)
    resp = await nexus_call(method, root + path, headers=headers, json=json_body)
    try:
        body = resp['json'] if resp['content'] else {}
    except Exception:
        body = {}
    if resp['status_code'] >= 400:
        return (resp, body, resp['status_code'], _sage_err(resp, body))
    return (resp, body, resp['status_code'], 'ok')

def _sage_wrap(payload, wrapper):
    payload = payload if isinstance(payload, dict) else {}
    if wrapper in payload:
        return payload
    return {wrapper: payload}
