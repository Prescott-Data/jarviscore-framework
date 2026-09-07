from typing import Any, Dict, List, Optional

async def streak_get_contact(contact_key: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Streak API: get contact. Official: https://streak.com/api#get_a_contact"""
    try:
        if not contact_key:
            return _st_dataset([], 400, 'contact_key is required')
        (root, _) = _st_root(base_url)
        root_v2 = root[:-3] + '/v2' if root.endswith('/v1') else root
        (headers, err) = _st_auth()
        if err:
            return _st_dataset([], 401, err)
        resp = await nexus_call('GET', root_v2 + '/contacts/' + str(contact_key), headers=headers)
        try:
            data = resp['json'] if resp['content'] else {}
        except Exception:
            data = {}
        if resp['status_code'] >= 400:
            return _st_dataset([], resp['status_code'], _st_err(resp))
        return _st_dataset([data] if isinstance(data, dict) else [], resp['status_code'], 'ok')
    except Exception as e:
        return _st_dataset([], 500, str(e))

def _st_root(base_url):
    root = (base_url or None or None or 'https://www.streak.com/api/v1').strip().rstrip('/')
    if not root.endswith('/v1'):
        if _host_is(root, 'streak.com') and '/v1' not in root:
            root = root + '/api/v1' if '/api' not in root else root + '/v1'
    return (root, None)

def _st_auth():
    import base64
    return ({'Accept': 'application/json'}, None)

def _st_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _st_err(resp):
    return (resp['body'] or f"HTTP {resp['status_code']}")[:1000]

def _host_is(url, *domains):
    """True only if url's hostname equals or is a subdomain of one of domains."""
    from urllib.parse import urlparse
    u = str(url or '').strip()
    if '://' not in u:
        u = 'https://' + u
    try:
        host = (urlparse(u).hostname or '').lower()
    except Exception:
        return False
    return any((host == d or host.endswith('.' + d) for d in domains))
