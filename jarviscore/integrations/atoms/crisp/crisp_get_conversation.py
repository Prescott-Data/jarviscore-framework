from typing import Any, Dict, List, Optional
CRISP_API = 'https://api.crisp.chat/v1'

async def crisp_get_conversation(conversation_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Get a conversation by session_id from crisp. HTTP Basic site_id:api_key. Official: https://docs.crisp.chat/references/rest-api/v1/"""
    try:
        if not conversation_id:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'conversation_id is required'}
        (headers, basic, site_id) = _crisp_auth()
        if not site_id or not basic:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': 'auth_info requires site_id and api_key for Basic auth'}
        api = _crisp_api_root(base_url)
        url = f'{api}/website/{site_id}/conversation/{conversation_id}'
        resp = await _crisp_get(url, headers, basic, None, timeout, verify_ssl)
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': resp['body'][:1000]}
        (data, message) = _crisp_parse(resp)
        records = _crisp_records(data, single=True)
        return {'records': records, 'data_count': len(records), 'status': resp['status_code'], 'message': message}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _crisp_api_root(base_url):
    root = (base_url or CRISP_API).rstrip('/')
    if root.endswith('/v1'):
        return root
    if 'crisp.chat' in root and '/v1' not in root:
        return root + '/v1'
    return root

def _crisp_auth(json_body=False):
    headers = {'Accept': 'application/json', 'X-Crisp-Tier': 'plugin'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    site_id = None or None
    basic = None
    return (headers, basic, site_id)

async def _crisp_get(url, headers, basic, params, timeout, verify_ssl):
    return await nexus_call('GET', url, headers=headers, params=params)

def _crisp_parse(resp):
    try:
        payload = resp['json'] if resp['body'] else {}
    except Exception:
        return (None, resp['body'][:1000])
    if isinstance(payload, dict) and payload.get('error'):
        reason = payload.get('reason') or payload.get('message') or 'Crisp API error'
        return (None, str(reason))
    if isinstance(payload, dict) and 'data' in payload:
        return (payload.get('data'), 'ok')
    return (payload, 'ok')

def _crisp_records(data, single=False):
    if single:
        if isinstance(data, dict):
            return [data]
        return []
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        return [data]
    return []
