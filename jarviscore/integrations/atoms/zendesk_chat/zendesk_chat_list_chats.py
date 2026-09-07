from typing import Any, Dict, List, Optional

async def zendesk_chat_list_chats(limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """zendesk_chat REST: list chats. Official: https://developer.zendesk.com/api-reference/live-chat/introduction/"""
    try:
        root, err = _root(base_url)
        if err:
            return _dataset([], 400, err)
        headers, aerr = _auth()
        if aerr:
            return _dataset([], 401, aerr)
        resp = await nexus_call('GET', root + '/chats', headers=headers)
        if resp['status_code'] >= 400:
            return _dataset([], resp['status_code'], _err(resp))
        data = resp['json'] if resp['content'] else {}
        if isinstance(data, list):
            records = data
        elif isinstance(data, dict):
            docs = data.get('docs')
            records = list(docs.values()) if isinstance(docs, dict) else data.get('chats') or data.get('items') or data.get('data') or [data]
        else:
            records = []
        if not isinstance(records, list):
            records = [records]
        return _dataset(records, resp['status_code'], 'ok')
    except Exception as e:
        return _dataset([], 500, str(e))

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

def _dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _err(resp):
    return (resp['body'] or f'HTTP {resp['status_code']}')[:1000]
