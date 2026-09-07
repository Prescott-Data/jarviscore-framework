from typing import Any, Dict, List, Optional

async def twilio_update_call(call_sid: str, status: str='completed', timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Twilio REST: update call. Official: https://www.twilio.com/docs/usage/api"""
    try:
        (root, err) = _tw_root(base_url)
        if err:
            return _tw_provision({}, 400, err)
        if not call_sid:
            return _tw_provision({}, 400, 'call_sid is required')
        (sid, token, aerr) = _tw_account()
        if aerr:
            return _tw_provision({}, 401, aerr)
        resp = await nexus_call('POST', f'{root}/Calls/{call_sid}.json', data={'Status': status})
        if resp['status_code'] >= 400:
            return _tw_provision({}, resp['status_code'], _tw_err(resp))
        data = resp['json'] if resp['content'] else {}
        return _tw_provision(data if isinstance(data, dict) else {}, resp['status_code'], 'ok', fallback_id=call_sid)
    except Exception as e:
        return _tw_provision({}, 500, str(e))

def _tw_account():
    return (None, None, None)

def _tw_root(base_url):
    (sid, _, err) = _tw_account()
    if err:
        return (None, err)
    root = (base_url or None or f'https://api.twilio.com/2010-04-01/Accounts/{sid}').strip().rstrip('/')
    return (root, None)

def _tw_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get('sid') or obj.get('id') or fallback_id
    ids = [pid] if pid not in (None, '') else []
    rec = obj if obj else {'id': pid} if ids else {}
    return {'records': [rec] if rec else [], 'data_count': 1 if rec else 0, 'status': status, 'message': msg, 'provision_ids': ids}

def _tw_err(resp):
    return (resp['body'] or f"HTTP {resp['status_code']}")[:1000]
