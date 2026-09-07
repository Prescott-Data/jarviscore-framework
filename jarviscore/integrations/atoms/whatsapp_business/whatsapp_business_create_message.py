from typing import Any, Dict, List, Optional
_WA_ROOT = 'https://graph.facebook.com/v19.0'

async def whatsapp_business_create_message(to: str, text: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """WhatsApp Cloud API: Send text message. Official: https://developers.facebook.com/docs/whatsapp/cloud-api"""
    try:
        (root, _) = _wa_root(base_url)
        (headers, aerr) = _wa_auth()
        if aerr:
            return _wa_provision({}, 401, aerr)
        (pid, err) = _wa_phone()
        if err:
            return _wa_provision({}, 400, err)
        if not to or not text:
            return _wa_provision({}, 400, 'to and text are required')
        headers['Content-Type'] = 'application/json'
        body = {'messaging_product': 'whatsapp', 'to': to, 'type': 'text', 'text': {'body': text}}
        resp = await nexus_call('POST', f'{root}/{pid}/messages', headers=headers, json=body)
        if resp['status_code'] >= 400:
            return _wa_provision({}, resp['status_code'], _wa_err(resp))
        data = resp['json'] if resp['content'] else {}
        return _wa_provision(data if isinstance(data, dict) else {}, resp['status_code'], 'ok')
    except Exception as e:
        return _wa_provision({}, 500, str(e))

def _wa_root(base_url):
    root = (base_url or None or _WA_ROOT).strip().rstrip('/')
    return (root, None)

def _wa_auth():
    return ({'Accept': 'application/json'}, None)

def _wa_phone():
    pid = None or None
    if not pid:
        return (None, 'auth_info.phone_number_id is required')
    return (str(pid), None)

def _wa_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    msgs = obj.get('messages') if isinstance(obj.get('messages'), list) else []
    pid = (msgs[0].get('id') if msgs else None) or obj.get('id') or fallback_id
    ids = [pid] if pid not in (None, '') else []
    rec = obj if obj else {'id': pid} if ids else {}
    return {'records': [rec] if rec else [], 'data_count': 1 if rec else 0, 'status': status, 'message': msg, 'provision_ids': ids}

def _wa_err(resp):
    return (resp['body'] or f"HTTP {resp['status_code']}")[:1000]
