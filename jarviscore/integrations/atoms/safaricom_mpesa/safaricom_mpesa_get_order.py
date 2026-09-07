from typing import Any, Dict, List, Optional

async def safaricom_mpesa_get_order(order_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Query STK Push status by CheckoutRequestID. Official: https://developer.safaricom.co.ke/"""
    try:
        if not order_id:
            return _mp_dataset([], 400, 'order_id (CheckoutRequestID) is required')
        shortcode = None or None
        passkey = None or None
        if not shortcode or not passkey:
            return _mp_dataset([], 400, 'auth_info.business_short_code and passkey are required')
        ts = _mp_timestamp()
        body_payload = {'BusinessShortCode': str(shortcode), 'Password': _mp_password(shortcode, passkey, ts), 'Timestamp': ts, 'CheckoutRequestID': str(order_id)}
        resp, body, status, msg = await _mp_post('/mpesa/stkpushquery/v1/query', base_url, body_payload, timeout, verify_ssl)
        if status >= 400:
            return _mp_dataset([], status, msg)
        rec = body if isinstance(body, dict) else {}
        return _mp_dataset([rec] if rec else [], status, msg)
    except Exception as e:
        return _mp_dataset([], 500, str(e))

def _mp_root(base_url):
    root = (base_url or None or None or None or 'https://sandbox.safaricom.co.ke').strip().rstrip('/')
    for suffix in ('/oauth/v1/generate', '/mpesa/stkpush/v1/processrequest'):
        if suffix in root:
            root = root.split(suffix)[0]
    return (root, None)

def _mp_timestamp():
    import datetime
    return datetime.datetime.now().strftime('%Y%m%d%H%M%S')

def _mp_password(shortcode, passkey, timestamp):
    import base64
    raw = str(shortcode) + str(passkey) + str(timestamp)
    return base64.b64encode(raw.encode('utf-8')).decode('ascii')

async def _mp_oauth(base_url, timeout, verify_ssl):
    import base64
    root, _ = _mp_root(base_url)
    resp = await nexus_call('GET', root + '/oauth/v1/generate', params={'grant_type': 'client_credentials'}, headers={'Accept': 'application/json'})
    try:
        body = resp['json'] if resp['content'] else {}
    except Exception:
        body = {}
    if resp['status_code'] >= 400 or not body.get('access_token'):
        return (None, (body.get('errorMessage') or body.get('error') or resp['body'] or 'oauth failed')[:1000])
    return (str(body.get('access_token')).strip(), None)

def _mp_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _mp_err(resp, body=None):
    if isinstance(body, dict):
        err = body.get('errorMessage') or body.get('errorMessage') or body.get('error')
        if not err:
            err = body.get('ResponseDescription') or body.get('ResultDesc')
        if err:
            return str(err)[:1000]
    return (resp['body'] if resp is not None else 'request failed')[:1000]

async def _mp_post(path, base_url, json_body, timeout, verify_ssl):
    token, err = await _mp_oauth(base_url, timeout, verify_ssl)
    if err:
        return (None, None, 401, err)
    root, _ = _mp_root(base_url)
    resp = await nexus_call('POST', root + path, headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json', 'Accept': 'application/json'}, json=json_body)
    try:
        body = resp['json'] if resp['content'] else {}
    except Exception:
        body = {}
    if resp['status_code'] >= 400:
        return (resp, body, resp['status_code'], _mp_err(resp, body))
    if isinstance(body, dict) and str(body.get('ResponseCode', '0')) not in ('0', '0.0'):
        return (resp, body, 400, _mp_err(resp, body))
    return (resp, body, resp['status_code'], 'ok')
