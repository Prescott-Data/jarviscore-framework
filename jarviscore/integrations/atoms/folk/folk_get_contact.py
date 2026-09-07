from typing import Any, Dict, List, Optional
_FOLK_API_HOST = 'https://api.folk.app'

async def folk_get_contact(contact_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Get person (GET /v1/people/{personId}). contact_id is personId. Bearer API key in Authorization header per Folk External API. Official: https://developer.folk.app/"""
    try:
        if not contact_id:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'contact_id (personId) is required'}
        (api, err) = _folk_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        (headers, auth_err) = _folk_auth()
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        person_id = str(contact_id).strip()
        resp = await nexus_call('GET', f'{api}/people/{person_id}', headers=headers)
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': resp['body'][:1000]}
        data = resp['json'] if resp['body'] else {}
        records = _folk_single_record(data)
        return {'records': records, 'data_count': len(records), 'status': resp['status_code'], 'message': 'ok'}
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

def _folk_single_record(data):
    if isinstance(data, dict) and isinstance(data.get('data'), dict):
        return [data['data']]
    return []
