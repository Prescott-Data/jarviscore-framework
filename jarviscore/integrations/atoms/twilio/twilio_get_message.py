from typing import Any, Dict, List, Optional

async def twilio_get_message(message_sid: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Twilio REST: get message. Official: https://www.twilio.com/docs/usage/api"""
    try:
        root, err = _tw_root(base_url)
        if err:
            return _tw_dataset([], 400, err)
        if not message_sid:
            return _tw_dataset([], 400, 'message_sid is required')
        sid, token, aerr = _tw_account()
        if aerr:
            return _tw_dataset([], 401, aerr)
        resp = await nexus_call('GET', f'{root}/Messages/{message_sid}.json')
        if resp['status_code'] >= 400:
            return _tw_dataset([], resp['status_code'], _tw_err(resp))
        data = resp['json'] if resp['content'] else {}
        return _tw_dataset([data] if isinstance(data, dict) else [], resp['status_code'], 'ok')
    except Exception as e:
        return _tw_dataset([], 500, str(e))

def _tw_account():
    return (None, None, None)

def _tw_root(base_url):
    sid, _, err = _tw_account()
    if err:
        return (None, err)
    root = (base_url or None or f'https://api.twilio.com/2010-04-01/Accounts/{sid}').strip().rstrip('/')
    return (root, None)

def _tw_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _tw_err(resp):
    return (resp['body'] or f'HTTP {resp['status_code']}')[:1000]
