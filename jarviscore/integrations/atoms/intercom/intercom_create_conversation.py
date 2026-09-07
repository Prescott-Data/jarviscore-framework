from typing import Any, Dict, List, Optional
INTERCOM_API = 'https://api.intercom.io'

async def intercom_create_conversation(payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Create Intercom conversation. Official: https://developers.intercom.com/docs/references/rest-api/api.intercom.io/conversations"""
    try:
        if not payload:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'payload is required'}
        api, err = _ic_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        headers, auth_err = _ic_auth(json_body=True)
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err, 'provision_ids': []}
        resp = await _ic_post(f'{api}/conversations', headers, payload, timeout, verify_ssl)
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': resp['body'][:1000]}
        data = resp['json'] if resp['body'] else {}
        records = _ic_single(data)
        return {'records': records, 'data_count': len(records), 'status': resp['status_code'], 'message': 'ok', 'provision_ids': _ic_provision_id(data)}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _ic_api_root(base_url):
    root = (base_url or INTERCOM_API).rstrip('/')
    if 'intercom.io' not in root:
        return (None, 'base_url must be https://api.intercom.io')
    return (root, None)

def _ic_auth(json_body=False):
    headers = {'Accept': 'application/json', 'Intercom-Version': '2.11'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

async def _ic_post(url, headers, body, timeout, verify_ssl):
    return await nexus_call('POST', url, headers=headers, json=body)

def _ic_single(data):
    if isinstance(data, dict) and data.get('id') is not None:
        return [data]
    return []

def _ic_provision_id(data):
    recs = _ic_single(data)
    if recs:
        return [recs[0]['id']]
    return []
