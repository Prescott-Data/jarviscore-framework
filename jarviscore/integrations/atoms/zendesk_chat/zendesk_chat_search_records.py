from typing import Any, Dict, List, Optional

async def zendesk_chat_search_records(query: str, limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """zendesk_chat REST: search. Official: https://developer.zendesk.com/api-reference/live-chat/introduction/"""
    try:
        (root, err) = _root(base_url)
        if err:
            return _dataset([], 400, err)
        if not query:
            return _dataset([], 400, 'query is required')
        (headers, aerr) = _auth()
        if aerr:
            return _dataset([], 401, aerr)
        resp = await nexus_call('GET', root + '/chats/search', headers=headers, params={'q': query})
        if resp['status_code'] >= 400:
            return _dataset([], resp['status_code'], _err(resp))
        data = resp['json'] if resp['content'] else {}
        records = data.get('results') if isinstance(data, dict) else data if isinstance(data, list) else []
        if not isinstance(records, list):
            records = []
        return _dataset(records[:limit], resp['status_code'], 'ok')
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
    return (resp['body'] or f"HTTP {resp['status_code']}")[:1000]
