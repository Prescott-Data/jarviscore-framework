from typing import Any, Dict, List, Optional
GORGIAS_API = 'https://your-domain.gorgias.com/api'

async def gorgias_get_conversation(conversation_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Retrieve a Gorgias ticket by ID. Official: https://developers.gorgias.com/reference/get-ticket"""
    try:
        if not conversation_id:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'conversation_id is required'}
        api, err = _gorgias_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        headers, basic, auth_err = _gorgias_require_auth()
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        resp = await _gorgias_get(f'{api}/tickets/{conversation_id}', headers, basic, None, timeout, verify_ssl)
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': resp['body'][:1000]}
        records = _gorgias_single_record(resp['json'] if resp['body'] else {})
        return {'records': records, 'data_count': len(records), 'status': resp['status_code'], 'message': 'ok'}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _gorgias_api_root(base_url):
    root = (base_url or GORGIAS_API).rstrip('/')
    if not root.endswith('/api'):
        if _host_is(root, 'gorgias.com'):
            root = root + '/api'
        else:
            return (None, 'base_url must be https://{domain}.gorgias.com/api')
    return (root, None)

def _gorgias_require_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (None, None, 'auth_info requires username and password')

async def _gorgias_get(url, headers, basic, params, timeout, verify_ssl):
    return await nexus_call('GET', url, headers=headers, params=params)

def _gorgias_single_record(data):
    if isinstance(data, dict):
        if isinstance(data.get('data'), dict):
            return [data['data']]
        if data.get('id') is not None:
            return [data]
    return []

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
