from typing import Any, Dict, List, Optional
CAPSULE_API = 'https://api.capsulecrm.com'

async def capsulecrm_get_account(account_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Get Account via Capsule CRM API. Official: https://developer.capsulecrm.com/v2/operations/Party"""
    try:
        if not account_id:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'account_id is required'}
        api = _capsule_api_root(base_url)
        (headers, auth_err) = _capsule_auth()
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        resp = await _capsule_get(f'{api}/parties/{account_id}', headers, None, timeout, verify_ssl)
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': resp['body'][:1000]}
        data = resp['json'] if resp['body'] else {}
        records = _capsule_records_from(data, 'parties', 'party')
        return {'records': records, 'data_count': len(records), 'status': resp['status_code'], 'message': 'ok'}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _capsule_api_root(base_url):
    root = (base_url or CAPSULE_API).rstrip('/')
    if root.endswith('/api/v2'):
        return root
    if root.endswith('/api'):
        return root + '/v2'
    if '/api/v2' not in root:
        return root + '/api/v2'
    return root

def _capsule_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

async def _capsule_get(url, headers, params, timeout, verify_ssl):
    return await nexus_call('GET', url, headers=headers, params=params)

def _capsule_records_from(data, list_key, single_key):
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    if single_key and isinstance(data.get(single_key), dict):
        return [data[single_key]]
    items = data.get(list_key)
    if isinstance(items, list):
        return items
    return [data]
