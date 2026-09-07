from typing import Any, Dict, List, Optional

async def tawkto_get_conversation(chat_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Tawk.to REST: get chat. Official: https://developer.tawk.to/rest-api/"""
    try:
        root, _ = _tk_root(base_url)
        pid, err = _tk_property()
        if err:
            return _tk_dataset([], 400, err)
        if not chat_id:
            return _tk_dataset([], 400, 'chat_id is required')
        headers, aerr = _tk_auth()
        if aerr:
            return _tk_dataset([], 401, aerr)
        key = str((None or {}).get('api_key') or '').strip()
        resp = await nexus_call('POST', f'{root}/v1/chat.get', headers=headers, json={'propertyId': pid, 'chatId': chat_id})
        if resp['status_code'] >= 400:
            return _tk_dataset([], resp['status_code'], _tk_err(resp))
        data = resp['json'] if resp['content'] else {}
        record = data.get('data') if isinstance(data, dict) and 'data' in data else data
        return _tk_dataset([record] if isinstance(record, dict) and record else [], resp['status_code'], 'ok')
    except Exception as e:
        return _tk_dataset([], 500, str(e))

def _tk_root(base_url):
    root = (base_url or None or 'https://api.tawk.to').strip().rstrip('/')
    return (root, None)

def _tk_auth():
    return ({'Accept': 'application/json', 'Content-Type': 'application/json'}, None)

def _tk_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _tk_err(resp):
    return (resp['body'] or f'HTTP {resp['status_code']}')[:1000]

def _tk_property():
    pid = None or None
    if not pid:
        return (None, 'auth_info.property_id is required')
    return (str(pid), None)
