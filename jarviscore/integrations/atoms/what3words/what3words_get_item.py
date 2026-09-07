from typing import Any, Dict, List, Optional
_W3W_ROOT = 'https://api.what3words.com/v3'

async def what3words_get_item(words: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """what3words Public API: Convert 3wa to coordinates. Official: https://developer.what3words.com/public-api/docs"""
    'Convert 3 word address to coordinates.'
    try:
        (root, _) = _w3w_root(base_url)
        (key, err) = _w3w_key()
        if err:
            return _w3w_dataset([], 401, err)
        if not words:
            return _w3w_dataset([], 400, 'words is required')
        resp = await nexus_call('GET', f'{root}/convert-to-coordinates', params={'words': words, 'key': key})
        if resp['status_code'] >= 400:
            return _w3w_dataset([], resp['status_code'], _w3w_err(resp))
        data = resp['json'] if resp['content'] else {}
        return _w3w_dataset([data] if isinstance(data, dict) else [], resp['status_code'], 'ok')
    except Exception as e:
        return _w3w_dataset([], 500, str(e))

def _w3w_root(base_url):
    root = (base_url or None or _W3W_ROOT).strip().rstrip('/')
    return (root, None)

def _w3w_key():
    return (None, None)

def _w3w_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _w3w_err(resp):
    return (resp['body'] or f"HTTP {resp['status_code']}")[:1000]
