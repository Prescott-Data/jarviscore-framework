from typing import Any, Dict, List, Optional
_PEOPLE_API_ROOT = 'https://people.googleapis.com/v1'

async def google_people_get_user_profile(person_fields: str='names,emailAddresses,phoneNumbers,organizations', timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Get the authenticated user's People profile. Official: https://developers.google.com/people/api/rest/v1/people/get"""
    try:
        (api, err) = _people_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        (headers, auth_err) = _people_auth()
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        url = f'{api}/people/me'
        resp = await nexus_call('GET', url, headers=headers, params={'personFields': person_fields})
        status = resp['status_code']
        if status >= 400:
            return {'records': [], 'data_count': 0, 'status': status, 'message': resp['body'][:1000]}
        data = resp['json'] if resp['body'] else {}
        records = [data] if isinstance(data, dict) and data else []
        return {'records': records, 'data_count': len(records), 'status': status, 'message': 'ok'}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _people_api_root(base_url: str):
    root = (base_url or _PEOPLE_API_ROOT).rstrip('/')
    if 'people.googleapis.com' not in root:
        return (None, 'base_url must be People API root (https://people.googleapis.com/v1)')
    return (root, None)

def _people_auth() -> tuple:
    headers = {'Accept': 'application/json'}
    return (headers, None)
