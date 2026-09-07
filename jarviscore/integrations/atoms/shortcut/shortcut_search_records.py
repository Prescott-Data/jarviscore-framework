from typing import Any, Dict, List, Optional

async def shortcut_search_records(query: str, limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Shortcut API v3: search stories. Official: https://developer.shortcut.com/api/rest/v3#Stories/searchStories"""
    try:
        if not query:
            return _sc_dataset([], 400, 'query is required')
        root, _ = _sc_root(base_url)
        headers, err = _sc_auth()
        if err:
            return _sc_dataset([], 401, err)
        cap = _sc_cap(limit)
        resp = await nexus_call('GET', root + '/search/stories', headers=headers, params={'query': query, 'page_size': cap})
        try:
            data = resp['json'] if resp['content'] else {}
        except Exception:
            data = {}
        if resp['status_code'] >= 400:
            return _sc_dataset([], resp['status_code'], _sc_err(resp))
        records = [x for x in data.get('data') or data.get('stories') or [] if isinstance(x, dict)][:cap]
        if not records and isinstance(data, list):
            records = [x for x in data if isinstance(x, dict) and _sc_match(x, query)][:cap]
        return _sc_dataset(records, resp['status_code'], 'ok')
    except Exception as e:
        return _sc_dataset([], 500, str(e))

def _sc_root(base_url):
    root = (base_url or None or None or 'https://api.app.shortcut.com/api/v3').strip().rstrip('/')
    if not root.endswith('/v3'):
        if _host_is(root, 'shortcut.com') and '/v3' not in root:
            root = root + '/api/v3' if '/api' not in root else root + '/v3'
    return (root, None)

def _sc_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _sc_cap(limit):
    return min(max(int(limit or 25), 1), 250)

def _sc_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _sc_err(resp):
    try:
        data = resp['json']
        if isinstance(data, dict):
            msg = data.get('message') or data.get('error')
            if msg:
                return str(msg)[:1000]
    except Exception:
        pass
    return (resp['body'] or f'HTTP {resp['status_code']}')[:1000]

def _sc_match(record, query):
    q = str(query).lower()
    for key in ('id', 'name', 'description', 'story_type', 'workflow_state_id'):
        val = record.get(key)
        if val is not None and q in str(val).lower():
            return True
    return False

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
