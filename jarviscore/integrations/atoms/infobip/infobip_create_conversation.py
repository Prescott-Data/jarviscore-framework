from typing import Any, Dict, List, Optional
INFOBIP_API = 'https://api.infobip.com'

async def infobip_create_conversation(payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Create an Infobip conversation. Official: https://www.infobip.com/docs/conversations/conversations-over-api/manage-conversations-over-api"""
    try:
        if not payload:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'payload is required'}
        (api, err) = _ib_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        (headers, auth_err) = _ib_auth(json_body=True)
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err, 'provision_ids': []}
        resp = await _ib_post(f'{api}/ccaas/1/conversations', headers, payload, timeout, verify_ssl)
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': resp['body'][:1000]}
        data = resp['json'] if resp['body'] else {}
        records = _ib_conversations(data)
        return {'records': records, 'data_count': len(records), 'status': resp['status_code'], 'message': 'ok', 'provision_ids': _ib_provision_id(data if isinstance(data, dict) else records[0] if records else {})}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _ib_api_root(base_url):
    root = (base_url or INFOBIP_API).rstrip('/')
    if 'infobip.com' not in root:
        return (None, 'base_url must be https://api.infobip.com (or your Infobip regional base URL)')
    return (root, None)

def _ib_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

async def _ib_post(url, headers, body, timeout, verify_ssl):
    return await nexus_call('POST', url, headers=headers, json=body)

def _ib_conversations(data):
    if isinstance(data, dict):
        conv = data.get('conversations')
        if isinstance(conv, list):
            return conv
        if isinstance(data.get('id'), str):
            return [data]
    return []

def _ib_provision_id(data):
    if isinstance(data, dict) and data.get('id') not in (None, ''):
        return [data['id']]
    return []
