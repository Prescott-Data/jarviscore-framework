from typing import Any, Dict, List, Optional

async def zendesk_chat_update_chat(chat_id: str, name: str='', limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """zendesk_chat REST: update chat. Official: https://developer.zendesk.com/api-reference/live-chat/introduction/"""
    try:
        root, err = _root(base_url)
        if err:
            return _provision({}, 400, err)
        if not chat_id:
            return _provision({}, 400, 'chat_id is required')
        headers, aerr = _auth()
        if aerr:
            return _provision({}, 401, aerr)
        headers['Content-Type'] = 'application/json'
        payload = {'visitor.name': name} if name else {}
        resp = await nexus_call('PUT', root + '/chats/' + str(chat_id), headers=headers, json=payload)
        if resp['status_code'] >= 400:
            return _provision({}, resp['status_code'], _err(resp))
        data = resp['json'] if resp['content'] else {}
        return _provision(data if isinstance(data, dict) else {}, resp['status_code'], 'ok', fallback_id=chat_id)
    except Exception as e:
        return _provision({}, 500, str(e))

def _root(base_url):
    root = (base_url or None or '').strip().rstrip('/')
    if not root:
        sub = None or None
        if sub:
            root = 'https://' + str(sub).strip() + '.zendesk.com/api/v2/chat'
    if not root:
        return (None, 'base_url or auth_info.subdomain is required')
    return (root, None)

def _auth():
    return ({'Accept': 'application/json'}, None)

def _provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get('id') or obj.get('Id') or fallback_id
    ids = [pid] if pid not in (None, '') else []
    rec = obj if obj else {'id': pid} if ids else {}
    return {'records': [rec] if rec else [], 'data_count': 1 if rec else 0, 'status': status, 'message': msg, 'provision_ids': ids}

def _err(resp):
    return (resp['body'] or f'HTTP {resp['status_code']}')[:1000]
