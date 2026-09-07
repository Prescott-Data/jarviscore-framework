from typing import Any, Dict, List, Optional
LIVECHAT_AGENT_API = 'https://api.livechatinc.com/v3.6/agent'

async def livechat_create_conversation(payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Start a chat via start_chat action. Official: https://platform.text.com/docs/messaging/agent-chat-api#start-chat"""
    try:
        base, err = _lc_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err, 'provision_ids': []}
        body = payload if isinstance(payload, dict) else {}
        if body and 'chat' not in body and ('active' not in body) and ('continuous' not in body):
            body = {'chat': body}
        resp, aerr = await _lc_post(base, 'start_chat', body, timeout, verify_ssl)
        if aerr:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': aerr, 'provision_ids': []}
        data = _lc_json(resp)
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': _lc_error(data, resp['body']), 'provision_ids': []}
        result = _lc_provision(data, resp['status_code'])
        if not result['provision_ids'] and isinstance(data, dict) and data.get('chat_id'):
            result['provision_ids'] = [data['chat_id']]
            result['records'] = [{'id': data['chat_id'], 'thread_id': data.get('thread_id')}]
            result['data_count'] = 1
        return result
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e), 'provision_ids': []}

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

def _lc_provision_ids(data):
    if not isinstance(data, dict):
        return []
    for key in ('event_id', 'chat_id', 'thread_id', 'id'):
        val = data.get(key)
        if val not in (None, ''):
            return [val]
    return []

def _lc_provision(data, status, message='ok'):
    ids = _lc_provision_ids(data)
    records = [data] if isinstance(data, dict) and data else []
    if ids and (not records or not records[0].get('id')):
        records = [{'id': ids[0]}]
    return {'records': records, 'data_count': len(records), 'status': status, 'message': message, 'provision_ids': ids}
