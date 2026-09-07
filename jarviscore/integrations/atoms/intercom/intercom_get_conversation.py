from typing import Any, Dict, List, Optional
INTERCOM_API = 'https://api.intercom.io'

async def intercom_get_conversation(conversation_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Get Intercom conversation by ID. Official: https://developers.intercom.com/docs/references/rest-api/api.intercom.io/conversations"""
    try:
        if not conversation_id:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'conversation_id is required'}
        api, err = _ic_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        headers, auth_err = _ic_auth()
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        resp = await _ic_get(f'{api}/conversations/{conversation_id}', headers, None, timeout, verify_ssl)
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': resp['body'][:1000]}
        records = _ic_single(resp['json'] if resp['body'] else {})
        return {'records': records, 'data_count': len(records), 'status': resp['status_code'], 'message': 'ok'}
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

async def _ic_get(url, headers, params, timeout, verify_ssl):
    return await nexus_call('GET', url, headers=headers, params=params)

def _ic_single(data):
    if isinstance(data, dict) and data.get('id') is not None:
        return [data]
    return []
