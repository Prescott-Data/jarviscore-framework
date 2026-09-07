from typing import Any, Dict, List, Optional
INFOBIP_API = 'https://api.infobip.com'

async def infobip_update_conversation(conversation_id: str, payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Update an Infobip conversation. Official: https://www.infobip.com/docs/conversations/conversations-over-api/manage-conversations-over-api"""
    try:
        if not conversation_id:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'conversation_id is required'}
        if not payload:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'payload is required'}
        (api, err) = _ib_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        (headers, auth_err) = _ib_auth(json_body=True)
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        resp = await _ib_put(f'{api}/ccaas/1/conversations/{conversation_id}', headers, payload, timeout, verify_ssl)
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': resp['body'][:1000]}
        records = _ib_conversations(resp['json'] if resp['body'] else {})
        return {'records': records, 'data_count': len(records), 'status': resp['status_code'], 'message': 'ok'}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _ib_api_root(base_url):
    root = (base_url or INFOBIP_API).rstrip('/')
    if 'infobip.com' not in root:
        return (None, 'base_url must be https://api.infobip.com (or your Infobip regional base URL)')
    return (root, None)

def _ib_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

async def _ib_put(url, headers, body, timeout, verify_ssl):
    return await nexus_call('PUT', url, headers=headers, json=body)

def _ib_conversations(data):
    if isinstance(data, dict):
        conv = data.get('conversations')
        if isinstance(conv, list):
            return conv
        if isinstance(data.get('id'), str):
            return [data]
    return []
