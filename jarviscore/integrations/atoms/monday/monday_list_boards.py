from typing import Any, Dict, List, Optional
MONDAY_API = 'https://api.monday.com/v2'

async def monday_list_boards(limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """List boards via GraphQL boards query with page/limit. Official: https://developer.monday.com/api-reference/reference/boards"""
    try:
        base, err = _md_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        headers, aerr = _md_auth()
        if aerr:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': aerr}
        cap = _md_cap(limit)
        records: List[Dict[str, Any]] = []
        page = 1
        status = 200
        while len(records) < cap and page <= 50:
            q = 'query($limit: Int!, $page: Int!) { boards(limit: $limit, page: $page) { id name state board_kind description url workspace_id } }'
            resp = await _md_gql(base, headers, q, {'limit': min(cap - len(records), 100), 'page': page}, timeout, verify_ssl)
            data, status, msg = _md_parse(resp)
            if status >= 400 and (not data):
                return {'records': records, 'data_count': len(records), 'status': status, 'message': msg}
            batch = _md_records((data or {}).get('boards'))
            if not batch:
                break
            records.extend(batch)
            if len(batch) < min(cap - len(records) + len(batch), 100):
                break
            page += 1
        records = records[:cap]
        return {'records': records, 'data_count': len(records), 'status': status, 'message': 'ok'}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _md_root(base_url):
    root = (base_url or MONDAY_API).rstrip('/')
    if not _host_is(root, 'monday.com'):
        return (None, 'base_url must be https://api.monday.com/v2')
    if not root.endswith('/v2'):
        root = root + '/v2' if '/' not in root.split('://', 1)[-1] else root
    return (root, None)

def _md_auth():
    return ({'Content-Type': 'application/json', 'Accept': 'application/json'}, None)

async def _md_gql(base, headers, query, variables, timeout, verify_ssl):
    return await nexus_call('POST', base, headers=headers, json={'query': query, 'variables': variables or {}})

def _md_parse(resp):
    try:
        body = resp['json'] if resp['body'] else {}
    except Exception:
        body = {}
    if resp['status_code'] >= 400:
        return (None, resp['status_code'], (resp['body'] or f'HTTP {resp['status_code']}')[:1000])
    errors = body.get('errors')
    if errors:
        msg = errors[0].get('message') if isinstance(errors[0], dict) else str(errors[0])
        return (body.get('data'), 400, msg)
    return (body.get('data') or {}, resp['status_code'], 'ok')

def _md_cap(limit):
    return min(max(int(limit or 25), 1), 500)

def _md_records(items):
    if isinstance(items, list):
        return [x for x in items if isinstance(x, dict)]
    if isinstance(items, dict):
        return [items]
    return []

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
