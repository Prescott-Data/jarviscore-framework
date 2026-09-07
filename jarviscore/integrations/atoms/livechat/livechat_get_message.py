from typing import Any, Dict, List, Optional
LIVECHAT_AGENT_API = 'https://api.livechatinc.com/v3.6/agent'

async def livechat_get_message(conversation_id: str, message_id: str, thread_id: str='', timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Get event by ID from get_chat thread events. Official: https://platform.text.com/docs/messaging/agent-chat-api#get-chat"""
    try:
        cid = _lc_chat_id(conversation_id)
        if not cid:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'conversation_id is required'}
        if not message_id:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'message_id is required'}
        (base, err) = _lc_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        body = {'chat_id': cid}
        if thread_id:
            body['thread_id'] = thread_id
        (resp, aerr) = await _lc_post(base, 'get_chat', body, timeout, verify_ssl)
        if aerr:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': aerr}
        data = _lc_json(resp)
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': _lc_error(data, resp['body'])}
        events = []
        thread = data.get('thread') if isinstance(data, dict) else None
        if isinstance(thread, dict):
            events.extend(_lc_flatten_events([thread]))
        for ev in events:
            if str(ev.get('id')) == str(message_id):
                return {'records': [ev], 'data_count': 1, 'status': resp['status_code'], 'message': 'ok'}
        return {'records': [], 'data_count': 0, 'status': 404, 'message': 'message not found in chat thread'}
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
    (auth, err) = _lc_auth_header()
    if err:
        return (None, err)
    return ({'Accept': 'application/json', 'Content-Type': 'application/json', 'Authorization': auth}, None)

def _lc_action_url(base, action):
    if base.endswith('/agent'):
        return f'{base}/action/{action}'
    return f'{base}/action/{action}'

async def _lc_post(base, action, body, timeout, verify_ssl):
    (headers, err) = _lc_headers()
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

def _lc_chat_id(conversation_id, chat_id=None):
    return str(chat_id or conversation_id or '')

def _lc_flatten_events(threads):
    out = []
    for thread in threads if isinstance(threads, list) else []:
        if not isinstance(thread, dict):
            continue
        tid = thread.get('id')
        for ev in thread.get('events') or []:
            if isinstance(ev, dict):
                row = dict(ev)
                if tid and 'thread_id' not in row:
                    row['thread_id'] = tid
                out.append(row)
    return out
