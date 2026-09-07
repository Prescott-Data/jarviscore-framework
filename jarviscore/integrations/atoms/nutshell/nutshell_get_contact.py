from typing import Any, Dict, List, Optional
NUTSHELL_RPC = 'https://app.nutshell.com/api/v1/json'

async def nutshell_get_contact(contact_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Get Contact via Nutshell JSON-RPC. Official: https://developers-rpc.nutshell.com/detail/class_core.html#getContact"""
    try:
        if not contact_id:
            return _ns_dataset([], 400, 'contact_id is required')
        base, err = _ns_root(base_url)
        if err:
            return _ns_dataset([], 400, err)
        headers, aerr = _ns_auth()
        if aerr:
            return _ns_dataset([], 401, aerr)
        result, status, msg = await _ns_rpc(base, headers, 'getContact', {'contactId': int(contact_id) if str(contact_id).isdigit() else contact_id}, timeout, verify_ssl)
        if msg != 'ok':
            return _ns_dataset([], status, msg)
        return _ns_dataset(_ns_records(result), status, msg)
    except Exception as e:
        return _ns_dataset([], 500, str(e))

def _ns_root(base_url):
    root = (base_url or NUTSHELL_RPC).rstrip('/')
    if 'nutshell.com' not in root:
        return (None, 'base_url must be https://app.nutshell.com/api/v1/json')
    if not root.endswith('/json'):
        if root.endswith('/api/v1'):
            root = root + '/json'
        elif '/api/' not in root:
            root = root + '/api/v1/json'
    return (root, None)

def _ns_auth():
    import base64
    return ({'Accept': 'application/json', 'Content-Type': 'application/json'}, None)

async def _ns_rpc(base, headers, method, params, timeout, verify_ssl, req_id=1):
    body = {'jsonrpc': '2.0', 'method': method, 'params': params or {}, 'id': req_id}
    resp = await nexus_call('POST', base, headers=headers, json=body)
    status = resp['status_code']
    try:
        payload = resp['json'] if resp['body'] else {}
    except Exception:
        payload = {}
    if status >= 400:
        msg = resp['body'][:1000]
        if isinstance(payload, dict):
            err = payload.get('error')
            if isinstance(err, dict):
                msg = str(err.get('message') or err.get('data') or err)[:1000]
        return (None, status, msg)
    if isinstance(payload, dict) and payload.get('error'):
        err = payload['error']
        msg = str(err.get('message') if isinstance(err, dict) else err)[:1000]
        return (None, 400, msg)
    result = payload.get('result') if isinstance(payload, dict) else None
    return (result, status, 'ok')

def _ns_records(result):
    if isinstance(result, list):
        return [r for r in result if isinstance(r, dict)]
    if isinstance(result, dict):
        if result.get('id') is not None:
            return [result]
        for key in ('contacts', 'accounts', 'leads', 'results', 'stubs'):
            val = result.get(key)
            if isinstance(val, list):
                return [r for r in val if isinstance(r, dict)]
    return []

def _ns_dataset(records, status, msg):
    return {'records': records, 'data_count': len(records), 'status': status, 'message': msg}
