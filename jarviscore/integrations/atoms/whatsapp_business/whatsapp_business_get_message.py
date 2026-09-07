from typing import Any, Dict, List, Optional
_WA_ROOT = 'https://graph.facebook.com/v19.0'

async def whatsapp_business_get_message(message_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """WhatsApp Cloud API: Get message by id. Official: https://developers.facebook.com/docs/whatsapp/cloud-api"""
    try:
        root, _ = _wa_root(base_url)
        headers, aerr = _wa_auth()
        if aerr:
            return _wa_dataset([], 401, aerr)
        if not message_id:
            return _wa_dataset([], 400, 'message_id is required')
        resp = await nexus_call('GET', f'{root}/{message_id}', headers=headers)
        if resp['status_code'] >= 400:
            return _wa_dataset([], resp['status_code'], _wa_err(resp))
        data = resp['json'] if resp['content'] else {}
        return _wa_dataset([data] if isinstance(data, dict) else [], resp['status_code'], 'ok')
    except Exception as e:
        return _wa_dataset([], 500, str(e))

def _wa_root(base_url):
    root = (base_url or None or _WA_ROOT).strip().rstrip('/')
    return (root, None)

def _wa_auth():
    return ({'Accept': 'application/json'}, None)

def _wa_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _wa_err(resp):
    return (resp['body'] or f'HTTP {resp['status_code']}')[:1000]
