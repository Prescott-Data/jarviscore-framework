from typing import Any, Dict, List, Optional
KLAVIYO_API = 'https://a.klaviyo.com'
KL_REVISION = '2024-10-15'

async def klaviyo_create_event(payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Create Klaviyo event. Official: https://developers.klaviyo.com/en/reference/get_events"""
    try:
        if not payload:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'payload is required'}
        api, err = _kv_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        headers, auth_err = _kv_auth(json_body=True)
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err, 'provision_ids': []}
        body = payload if isinstance(payload.get('data'), dict) else {'data': {'type': 'event', 'attributes': payload}}
        resp = await _kv_post(f'{api}/api/events/', headers, body, timeout, verify_ssl)
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': resp['body'][:1000]}
        data = resp['json'] if resp['body'] else {}
        records = _kv_jsonapi_records(data)
        return {'records': records, 'data_count': len(records), 'status': resp['status_code'], 'message': 'ok', 'provision_ids': _kv_provision_id(data)}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _kv_api_root(base_url):
    root = (base_url or KLAVIYO_API).rstrip('/')
    if 'klaviyo.com' not in root:
        return (None, 'base_url must be https://a.klaviyo.com')
    return (root, None)

def _kv_auth(json_body=False):
    headers = {'Accept': 'application/json', 'revision': KL_REVISION}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

async def _kv_post(url, headers, body, timeout, verify_ssl):
    return await nexus_call('POST', url, headers=headers, json=body)

def _kv_jsonapi_records(data):
    if isinstance(data, dict):
        d = data.get('data')
        if isinstance(d, list):
            return d
        if isinstance(d, dict):
            return [d]
    return []

def _kv_provision_id(data):
    if isinstance(data, dict):
        d = data.get('data')
        if isinstance(d, dict) and d.get('id'):
            return [d['id']]
    return []
