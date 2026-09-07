from typing import Any, Dict, List, Optional
MONDAY_API = 'https://api.monday.com/v2'

async def monday_update_item(item_id: str, payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Update item columns via GraphQL change_multiple_column_values. Official: https://developer.monday.com/api-reference/docs/change-column-values"""
    try:
        if not item_id:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'item_id is required', 'provision_ids': []}
        base, err = _md_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err, 'provision_ids': []}
        headers, aerr = _md_auth()
        if aerr:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': aerr, 'provision_ids': []}
        body = payload if isinstance(payload, dict) else {}
        board_id, berr = _md_board_id(body)
        if berr:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': berr, 'provision_ids': []}
        import json
        col_vals = body.get('column_values') if isinstance(body.get('column_values'), dict) else dict(body)
        for key in ('board_id', 'column_values', 'item_id'):
            col_vals.pop(key, None)
        if body.get('name') not in (None, ''):
            col_vals['name'] = body.get('name')
        if not col_vals:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'payload.column_values or updatable fields are required', 'provision_ids': []}
        q = 'mutation($board_id: ID!, $item_id: ID!, $column_values: JSON!) { change_multiple_column_values(board_id: $board_id, item_id: $item_id, column_values: $column_values) { id name } }'
        resp = await _md_gql(base, headers, q, {'board_id': str(board_id), 'item_id': str(item_id), 'column_values': json.dumps(col_vals)}, timeout, verify_ssl)
        data, status, msg = _md_parse(resp)
        if status >= 400:
            return {'records': [], 'data_count': 0, 'status': status, 'message': msg, 'provision_ids': []}
        out = _md_provision(data, 'change_multiple_column_values', fallback_id=item_id)
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
