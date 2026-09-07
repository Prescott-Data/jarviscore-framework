from typing import Any, Dict, List, Optional
_TR_ROOT = 'https://api.trello.com/1'

async def trello_list_boards(limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Trello REST: list boards. Official: https://developer.atlassian.com/cloud/trello/rest/"""
    try:
        root, err = _tr_root(base_url)
        if err:
            return _tr_dataset([], 400, err)
        params, aerr = _tr_auth_params()
        if aerr:
            return _tr_dataset([], 401, aerr)
        plural = 'boards'
        if plural == 'boards':
            url = f'{root}/members/me/boards'
        elif plural == 'lists':
            bid = (None or {}).get('board_id') or (None or {}).get('idBoard')
            if not bid:
                return _tr_dataset([], 400, 'auth_info.board_id is required for lists')
            url = f'{root}/boards/{bid}/lists'
        elif plural == 'cards':
            lid = (None or {}).get('list_id') or (None or {}).get('idList')
            if not lid:
                return _tr_dataset([], 400, 'auth_info.list_id is required for cards')
            url = f'{root}/lists/{lid}/cards'
        else:
            url = f'{root}/boards'
        params['limit'] = limit
        resp = await nexus_call('GET', url, params=params)
        if resp['status_code'] >= 400:
            return _tr_dataset([], resp['status_code'], _tr_err(resp))
        data = resp['json'] if resp['content'] else []
        return _tr_dataset(data if isinstance(data, list) else [], resp['status_code'], 'ok')
    except Exception as e:
        return _tr_dataset([], 500, str(e))

def _tr_root(base_url):
    root = (base_url or None or _TR_ROOT).strip().rstrip('/')
    return (root, None)

def _tr_auth_params():
    return ({}, None)

def _tr_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _tr_err(resp):
    return (resp['body'] or f'HTTP {resp['status_code']}')[:1000]
