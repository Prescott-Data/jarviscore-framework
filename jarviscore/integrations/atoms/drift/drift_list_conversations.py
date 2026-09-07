from typing import Any, Dict, List, Optional
DRIFT_LIST_HOST = 'https://api.drift.com'

async def drift_list_conversations(timeout: int=30, verify_ssl: bool=True, limit: int=25, base_url: str=None) -> dict:
    """List conversations (GET https://api.drift.com/conversations/list). Bearer token via auth_info. Official: https://devdocs.drift.com/docs/list-conversations"""
    try:
        (headers, err) = _drift_auth()
        if err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': err}
        root = _drift_list_root(base_url)
        records = []
        cursor = None
        status = 0
        cap = min(max(int(limit or 25), 1), 100)
        while len(records) < cap:
            params = {'limit': min(cap - len(records), 100)}
            if cursor:
                params['page_token'] = cursor
            resp = await _drift_get(f'{root}/conversations/list', headers, params, timeout, verify_ssl)
            status = resp['status_code']
            if status >= 400:
                return {'records': records, 'data_count': len(records), 'status': status, 'message': resp['body'][:1000]}
            data = resp['json'] if resp['body'] else {}
            batch = data.get('data') or []
            for item in batch:
                if isinstance(item, dict):
                    records.append(item)
                    if len(records) >= cap:
                        break
            cursor = _drift_page_token(data.get('links'))
            if not cursor or not batch:
                break
        return {'records': records[:cap], 'data_count': len(records[:cap]), 'status': status, 'message': 'ok'}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _drift_list_root(base_url):
    root = (base_url or DRIFT_LIST_HOST).rstrip('/')
    if _host_is(root, 'driftapi.com'):
        root = root.replace('driftapi.com', 'api.drift.com')
    if root.endswith('/v1'):
        root = root[:-3]
    return root

def _drift_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

async def _drift_get(url, headers, params, timeout, verify_ssl):
    return await nexus_call('GET', url, headers=headers, params=params)

def _drift_page_token(links):
    if not isinstance(links, dict):
        return None
    nxt = str(links.get('next') or '')
    if not nxt:
        return None
    query = nxt.split('?', 1)[-1]
    param = 'page_' + 'token'
    for part in query.split('&'):
        if part.startswith(param + '='):
            return part.split('=', 1)[1]
    return None

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
