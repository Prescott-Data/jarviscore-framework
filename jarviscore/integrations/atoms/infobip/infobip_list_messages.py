from typing import Any, Dict, List, Optional
INFOBIP_API = 'https://api.infobip.com'

async def infobip_list_messages(conversation_id: Optional[str]=None, limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """List messages in an Infobip conversation. Official: https://www.infobip.com/docs/conversations/conversations-over-api/manage-calls-and-messages-over-api"""
    try:
        cid = _ib_conv_id(None, conversation_id)
        if not cid:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'conversation_id is required'}
        api, err = _ib_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        headers, auth_err = _ib_auth()
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        params = {'limit': min(max(limit, 1), 100)}
        resp = await _ib_get(f'{api}/ccaas/1/conversations/{cid}/messages', headers, params, timeout, verify_ssl)
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': resp['body'][:1000]}
        records = _ib_messages(resp['json'] if resp['body'] else {})[:limit]
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

async def _ib_get(url, headers, params, timeout, verify_ssl):
    return await nexus_call('GET', url, headers=headers, params=params)

def _ib_messages(data):
    if isinstance(data, dict):
        msgs = data.get('messages')
        if isinstance(msgs, list):
            return msgs
        if isinstance(data.get('id'), str):
            return [data]
    return []

def _ib_conv_id(payload, conversation_id=None):
    payload = payload if isinstance(payload, dict) else {}
    cid = conversation_id or payload.get('conversation_id') or payload.get('conversationId') or None or None
    return str(cid).strip() if cid not in (None, '') else None
