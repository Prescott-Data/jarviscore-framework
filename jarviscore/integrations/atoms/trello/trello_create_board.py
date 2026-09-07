from typing import Any, Dict, List, Optional
_TR_ROOT = 'https://api.trello.com/1'

async def trello_create_board(name: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Trello REST: create board. Official: https://developer.atlassian.com/cloud/trello/rest/"""
    try:
        root, err = _tr_root(base_url)
        if err:
            return _tr_provision({}, 400, err)
        if not name:
            return _tr_provision({}, 400, 'name is required')
        params, aerr = _tr_auth_params()
        if aerr:
            return _tr_provision({}, 401, aerr)
        params['name'] = name
        resp = await nexus_call('POST', f'{root}/boards', params=params)
        if resp['status_code'] >= 400:
            return _tr_provision({}, resp['status_code'], _tr_err(resp))
        data = resp['json'] if resp['content'] else {}
        return _tr_provision(data if isinstance(data, dict) else {}, resp['status_code'], 'ok')
    except Exception as e:
        return _tr_provision({}, 500, str(e))

def _tr_root(base_url):
    root = (base_url or None or _TR_ROOT).strip().rstrip('/')
    return (root, None)

def _tr_auth_params():
    return ({}, None)

def _tr_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get('id') or fallback_id
    ids = [pid] if pid not in (None, '') else []
    rec = obj if obj else {'id': pid} if ids else {}
    return {'records': [rec] if rec else [], 'data_count': 1 if rec else 0, 'status': status, 'message': msg, 'provision_ids': ids}

def _tr_err(resp):
    return (resp['body'] or f'HTTP {resp['status_code']}')[:1000]
