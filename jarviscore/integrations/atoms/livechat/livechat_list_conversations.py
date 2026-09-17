from typing import Any, Dict, List, Optional
LIVECHAT_AGENT_API = 'https://api.livechatinc.com/v3.6/agent'

async def livechat_list_conversations(limit: int=25, page_id: str='', timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """List agent chats via list_chats action. Official: https://platform.text.com/docs/messaging/agent-chat-api#list-chats"""
    try:
        (base, err) = _lc_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        body = {'limit': min(max(int(limit or 25), 1), 100)}
        if page_id:
            body['page_id'] = page_id
        records = []
        status = 0
        next_page = page_id or None
        pages = 0
        while len(records) < min(max(int(limit or 25), 1), 100) and pages < 20:
            pages += 1
            req = dict(body)
            if next_page:
                req['page_id'] = next_page
            (resp, aerr) = await _lc_post(base, 'list_chats', req, timeout, verify_ssl)
            if aerr:
                return {'records': [], 'data_count': 0, 'status': 401, 'message': aerr}
            status = resp['status_code']
            data = _lc_json(resp)
            if status >= 400:
                return {'records': records, 'data_count': len(records), 'status': status, 'message': _lc_error(data, resp['body'])}
            batch = _lc_records(data.get('chats_summary') if isinstance(data, dict) else None)
            records.extend(batch)
            next_page = data.get('next_page_id') if isinstance(data, dict) else None
            if not next_page or not batch:
                break
        records = _lc_cap(records, limit)
        return {'records': records, 'data_count': len(records), 'status': status, 'message': 'ok'}
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

def _lc_records(items):
    if isinstance(items, list):
        return [row for row in items if isinstance(row, dict)]
    if isinstance(items, dict) and items.get('id') is not None:
        return [items]
    return []

def _lc_cap(records, limit):
    cap = min(max(int(limit or 25), 1), 100)
    return records[:cap]
