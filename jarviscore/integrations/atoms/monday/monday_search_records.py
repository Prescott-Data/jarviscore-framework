from typing import Any, Dict, List, Optional
MONDAY_API = 'https://api.monday.com/v2'

async def monday_search_records(query: str, limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Search items by name via GraphQL items_page query_params contains_text. Official: https://developer.monday.com/api-reference/reference/items-page"""
    try:
        if not query:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'query is required'}
        base, err = _md_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        headers, aerr = _md_auth()
        if aerr:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': aerr}
        board_id, berr = _md_board_id()
        if berr:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': berr}
        query_params = {'rules': [{'column_id': 'name', 'compare_value': [str(query)], 'operator': 'contains_text'}]}
        records, status, msg = await _md_items_page(base, headers, board_id, limit, query_params, timeout, verify_ssl)
        return {'records': records, 'data_count': len(records), 'status': status, 'message': msg}
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

def _md_board_id(payload=None):
    payload = payload if isinstance(payload, dict) else {}
    bid = payload.get('board_id') or None
    if bid in (None, ''):
        return (None, 'board_id is required (payload.board_id or auth_info.board_id)')
    return (str(bid), None)

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

async def _md_items_page(base, headers, board_id, limit, query_params, timeout, verify_ssl):
    cap = _md_cap(limit)
    records = []
    cursor = None
    status = 200
    pages = 0
    while len(records) < cap and pages < 50:
        pages += 1
        batch_size = min(cap - len(records), 100)
        if cursor:
            q = 'query($cursor: String!, $limit: Int!) { next_items_page(cursor: $cursor, limit: $limit) { cursor items { id name state created_at updated_at url } } }'
            vars_ = {'cursor': cursor, 'limit': batch_size}
        else:
            q = 'query($board_id: [ID!], $limit: Int!, $query_params: ItemsQuery) { boards(ids: $board_id) { items_page(limit: $limit, query_params: $query_params) { cursor items { id name state created_at updated_at url } } } }'
            vars_ = {'board_id': [str(board_id)], 'limit': batch_size, 'query_params': query_params}
        resp = await _md_gql(base, headers, q, vars_, timeout, verify_ssl)
        data, status, msg = _md_parse(resp)
        if status >= 400 and (not data):
            return (records, status, msg)
        if cursor:
            page = (data or {}).get('next_items_page') or {}
        else:
            boards = (data or {}).get('boards') or []
            page = boards[0].get('items_page') if boards and isinstance(boards[0], dict) else {}
        items = _md_records((page or {}).get('items'))
        records.extend(items)
        cursor = (page or {}).get('cursor')
        if not items or not cursor:
            break
    return (records[:cap], status, 'ok')

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
