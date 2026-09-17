from typing import Any, Dict, List, Optional

async def sage_business_cloud_accounting_get_contact(contact_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Get contact by id. Official: https://developer.sage.com/accounting/reference/"""
    try:
        if not contact_id:
            return _sage_dataset([], 400, 'contact_id is required')
        (resp, body, status, msg) = await _sage_get(f'/contacts/{contact_id}', base_url, None, timeout, verify_ssl)
        if status >= 400:
            return _sage_dataset([], status, msg)
        rec = _sage_entity_obj(body, 'contact') or (body if isinstance(body, dict) else {})
        return _sage_dataset([rec] if rec else [], status, msg)
    except Exception as e:
        return _sage_dataset([], 500, str(e))

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

def _sage_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

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

async def _sage_get(path, base_url, params, timeout, verify_ssl):
    (headers, err) = _sage_auth()
    if err:
        return (None, None, 401, err)
    (root, _) = _sage_root(base_url)
    resp = await nexus_call('GET', root + path, headers=headers, params=params)
    try:
        body = resp['json'] if resp['content'] else {}
    except Exception:
        body = {}
    if resp['status_code'] >= 400:
        return (resp, body, resp['status_code'], _sage_err(resp, body))
    return (resp, body, resp['status_code'], 'ok')
