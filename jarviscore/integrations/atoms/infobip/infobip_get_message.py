from typing import Any, Dict, List, Optional
INFOBIP_API = 'https://api.infobip.com'

async def infobip_get_message(message_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Get an Infobip conversation message by ID. Official: https://www.infobip.com/docs/conversations/conversations-over-api/manage-calls-and-messages-over-api"""
    try:
        if not message_id:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'message_id is required'}
        api, err = _ib_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        headers, auth_err = _ib_auth()
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        cid = _ib_conv_id(None, None)
        if not cid:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'conversation_id is required (provide via auth_info.conversation_id); Infobip has no standalone get-message endpoint'}
        resp = await _ib_get(f'{api}/ccaas/1/conversations/{cid}/messages', headers, {'messageIds': message_id}, timeout, verify_ssl)
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': resp['body'][:1000]}
        records = [m for m in _ib_messages(resp['json'] if resp['body'] else {}) if str(m.get('id')) == str(message_id)]
        status = resp['status_code'] if records else 404
        return {'records': records, 'data_count': len(records), 'status': status, 'message': 'ok' if records else 'message not found'}
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
