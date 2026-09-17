from typing import Any, Dict, List, Optional
CAPSULE_API = 'https://api.capsulecrm.com'

async def capsulecrm_update_contact(contact_id: str, payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Update Contact via Capsule CRM API. Official: https://developer.capsulecrm.com/v2/operations/Party"""
    try:
        if not contact_id or not payload:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'contact_id and payload are required'}
        api = _capsule_api_root(base_url)
        (headers, auth_err) = _capsule_auth(json_body=True)
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        body = _capsule_wrap('party', payload)
        resp = await _capsule_put_json(f'{api}/parties/{contact_id}', headers, body, timeout, verify_ssl)
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': resp['body'][:1000]}
        data = resp['json'] if resp['body'] else {}
        records = _capsule_records_from(data, 'parties', 'party')
        return {'records': records, 'data_count': len(records), 'status': resp['status_code'], 'message': 'ok', 'provision_ids': [contact_id]}
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

async def _capsule_put_json(url, headers, body, timeout, verify_ssl):
    return await nexus_call('PUT', url, headers=headers, json=body)

def _capsule_wrap(kind, payload):
    if not isinstance(payload, dict):
        return {kind: payload}
    if kind in payload:
        return payload
    return {kind: payload}

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
