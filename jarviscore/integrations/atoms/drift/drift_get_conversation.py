from typing import Any, Dict, Optional
DRIFT_CONV_HOST = 'https://driftapi.com'

async def drift_get_conversation(conversation_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Get conversation by ID (GET https://driftapi.com/conversations/{conversation_id}). Bearer token via auth_info. Official: https://devdocs.drift.com/docs/retrieve-a-conversation"""
    try:
        if not conversation_id:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'conversation_id is required'}
        headers, err = _drift_auth()
        if err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': err}
        root = _drift_conv_root(base_url)
        resp = await _drift_get(f'{root}/conversations/{conversation_id}', headers, None, timeout, verify_ssl)
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': resp['body'][:1000]}
        data = resp['json'] if resp['body'] else {}
        obj = data.get('data') if isinstance(data, dict) else None
        records = [obj] if isinstance(obj, dict) else []
        return {'records': records, 'data_count': len(records), 'status': resp['status_code'], 'message': 'ok'}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _drift_conv_root(base_url):
    root = (base_url or DRIFT_CONV_HOST).rstrip('/')
    if _host_is(root, 'api.drift.com') and (not _host_is(root, 'driftapi.com')):
        root = root.replace('api.drift.com', 'driftapi.com')
    if root.endswith('/conversations'):
        root = root[:-len('/conversations')]
    return root

def _drift_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

async def _drift_get(url, headers, params, timeout, verify_ssl):
    return await nexus_call('GET', url, headers=headers, params=params)

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
