from typing import Any, Dict, List, Optional
MONDAY_API = 'https://api.monday.com/v2'

async def monday_create_board(payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Create board via GraphQL create_board mutation. Official: https://developer.monday.com/api-reference/reference/boards"""
    try:
        (base, err) = _md_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err, 'provision_ids': []}
        (headers, aerr) = _md_auth()
        if aerr:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': aerr, 'provision_ids': []}
        body = payload if isinstance(payload, dict) else {}
        board_name = body.get('board_name') or body.get('name')
        if not board_name:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'payload.board_name is required', 'provision_ids': []}
        board_kind = body.get('board_kind') or body.get('kind') or 'public'
        vars_ = {'board_name': str(board_name), 'board_kind': str(board_kind).lower()}
        if body.get('workspace_id') not in (None, ''):
            vars_['workspace_id'] = str(body.get('workspace_id'))
        if body.get('description') not in (None, ''):
            vars_['description'] = str(body.get('description'))
        q = 'mutation($board_name: String!, $board_kind: BoardKind!, $workspace_id: ID, $description: String) { create_board(board_name: $board_name, board_kind: $board_kind, workspace_id: $workspace_id, description: $description) { id name url state board_kind } }'
        resp = await _md_gql(base, headers, q, vars_, timeout, verify_ssl)
        (data, status, msg) = _md_parse(resp)
        if status >= 400:
            return {'records': [], 'data_count': 0, 'status': status, 'message': msg, 'provision_ids': []}
        out = _md_provision(data, 'create_board')
        out['status'] = status
        return out
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e), 'provision_ids': []}

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
        return (None, resp['status_code'], (resp['body'] or f"HTTP {resp['status_code']}")[:1000])
    errors = body.get('errors')
    if errors:
        msg = errors[0].get('message') if isinstance(errors[0], dict) else str(errors[0])
        return (body.get('data'), 400, msg)
    return (body.get('data') or {}, resp['status_code'], 'ok')

def _md_provision(data, key, fallback_id=None):
    obj = (data or {}).get(key) if isinstance(data, dict) else None
    if isinstance(obj, list):
        obj = obj[0] if obj else None
    if isinstance(obj, dict):
        pid = obj.get('id') or fallback_id
        ids = [pid] if pid not in (None, '') else []
        return {'records': [obj], 'data_count': 1, 'status': 200, 'message': 'ok', 'provision_ids': ids}
    if obj is True or obj is not None:
        ids = [fallback_id] if fallback_id not in (None, '') else []
        rec = {'id': fallback_id, 'success': True} if ids else {'success': True}
        return {'records': [rec], 'data_count': 1, 'status': 200, 'message': 'ok', 'provision_ids': ids}
    return {'records': [], 'data_count': 0, 'status': 400, 'message': 'mutation returned no data', 'provision_ids': []}

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
