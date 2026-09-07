from typing import Any, Dict, List, Optional
_FOLK_API_HOST = 'https://api.folk.app'

async def folk_create_deal(group_id: str, payload: Dict[str, Any], object_type: str='Deals', timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Create deal (POST /v1/groups/{groupId}/Deals JSON body). Bearer API key in Authorization header per Folk External API. Official: https://developer.folk.app/"""
    try:
        if not payload or not isinstance(payload, dict):
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'payload is required'}
        api, err = _folk_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        gid, otype, err = _folk_deal_scope(group_id, object_type)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        headers, auth_err = _folk_auth(json_body=True)
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        resp = await nexus_call('POST', f'{api}/groups/{gid}/{otype}', headers=headers, json=payload)
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': resp['body'][:1000]}
        data = resp['json'] if resp['body'] else {}
        records = _folk_single_record(data)
        return {'records': records, 'data_count': len(records), 'status': resp['status_code'], 'message': 'ok', 'provision_ids': _folk_provision_id(data)}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _folk_api_root(base_url: str):
    root = (base_url or _FOLK_API_HOST).rstrip('/')
    if not root:
        return (None, 'base_url is required (https://api.folk.app)')
    if root.endswith('/v1'):
        root = root[:-3]
    if not root.endswith('folk.app'):
        return (None, 'base_url must be the Folk API root (https://api.folk.app)')
    return (f'{root}/v1', None)

def _folk_auth(json_body: bool=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _folk_deal_scope(group_id, object_type):
    gid = group_id or None
    otype = object_type or None or 'Deals'
    if not gid:
        return (None, None, 'group_id is required for deals (or auth_info.group_id)')
    return (str(gid).strip(), str(otype).strip(), None)

def _folk_single_record(data):
    if isinstance(data, dict) and isinstance(data.get('data'), dict):
        return [data['data']]
    return []

def _folk_provision_id(data):
    recs = _folk_single_record(data)
    if recs and recs[0].get('id') not in (None, ''):
        return [str(recs[0]['id'])]
    return []
