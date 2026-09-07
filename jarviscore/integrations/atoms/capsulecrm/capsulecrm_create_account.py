from typing import Any, Dict, List, Optional
CAPSULE_API = 'https://api.capsulecrm.com'

async def capsulecrm_create_account(payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Create Account via Capsule CRM API. Official: https://developer.capsulecrm.com/v2/operations/Party"""
    try:
        if not payload:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'payload is required'}
        api = _capsule_api_root(base_url)
        headers, auth_err = _capsule_auth(json_body=True)
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        body = _capsule_party_body(payload, default_type='organisation')
        resp = await _capsule_post_json(f'{api}/parties', headers, body, timeout, verify_ssl)
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': resp['body'][:1000]}
        data = resp['json'] if resp['body'] else {}
        records = _capsule_records_from(data, 'parties', 'party')
        prov = [_capsule_provision_id(records[0])] if records else []
        prov = [x for x in prov if x is not None]
        return {'records': records, 'data_count': len(records), 'status': resp['status_code'], 'message': 'ok', 'provision_ids': prov}
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

async def _capsule_post_json(url, headers, body, timeout, verify_ssl):
    return await nexus_call('POST', url, headers=headers, json=body)

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

def _capsule_party_body(payload, default_type=None):
    body = _capsule_wrap('party', payload)
    party = body.get('party')
    if isinstance(party, dict) and default_type and (not party.get('type')):
        party = dict(party)
        party['type'] = default_type
        body['party'] = party
    return body

def _capsule_provision_id(record):
    if not isinstance(record, dict):
        return None
    if record.get('id') is not None:
        return record.get('id')
    for key in ('party', 'organisation', 'opportunity'):
        val = record.get(key)
        if isinstance(val, dict) and val.get('id') is not None:
            return val.get('id')
    return None
