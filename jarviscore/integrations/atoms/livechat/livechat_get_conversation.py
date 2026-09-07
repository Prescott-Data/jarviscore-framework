from typing import Any, Dict, List, Optional
LIVECHAT_AGENT_API = 'https://api.livechatinc.com/v3.6/agent'

async def livechat_get_conversation(conversation_id: str, thread_id: str='', timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Get chat by ID via get_chat action. Official: https://platform.text.com/docs/messaging/agent-chat-api#get-chat"""
    try:
        cid = _lc_chat_id(conversation_id)
        if not cid:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'conversation_id is required'}
        base, err = _lc_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        body = {'chat_id': cid}
        if thread_id:
            body['thread_id'] = thread_id
        resp, aerr = await _lc_post(base, 'get_chat', body, timeout, verify_ssl)
        if aerr:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': aerr}
        data = _lc_json(resp)
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': _lc_error(data, resp['body'])}
        records = _lc_records(data)
        return {'records': records, 'data_count': len(records), 'status': resp['status_code'], 'message': 'ok'}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _lc_root(base_url):
    root = (base_url or LIVECHAT_AGENT_API).rstrip('/')
    if 'livechatinc.com' not in root:
        return (None, 'base_url must be https://api.livechatinc.com/v3.6/agent')
    return (root, None)

def _lc_auth_header():
    import base64
    return (None, None)

def _lc_headers():
    auth, err = _lc_auth_header()
    if err:
        return (None, err)
    return ({'Accept': 'application/json', 'Content-Type': 'application/json', 'Authorization': auth}, None)

def _lc_action_url(base, action):
    if base.endswith('/agent'):
        return f'{base}/action/{action}'
    return f'{base}/action/{action}'

async def _lc_post(base, action, body, timeout, verify_ssl):
    headers, err = _lc_headers()
    if err:
        return (None, err)
    resp = await nexus_call('POST', _lc_action_url(base, action), headers=headers, json=body or {})
    return (resp, None)

def _lc_json(resp):
    try:
        return resp['json'] if resp['body'] else {}
    except Exception:
        return {}

def _lc_error(data, fallback=''):
    if isinstance(data, dict):
        err = data.get('error')
        if isinstance(err, dict):
            return str(err.get('message') or err.get('type') or fallback)[:1000]
        if data.get('type') == 'Error':
            return str(data.get('message') or fallback)[:1000]
    return (fallback or '')[:1000]

def _lc_records(items):
    if isinstance(items, list):
        return [row for row in items if isinstance(row, dict)]
    if isinstance(items, dict) and items.get('id') is not None:
        return [items]
    return []

def _lc_chat_id(conversation_id, chat_id=None):
    return str(chat_id or conversation_id or '')
