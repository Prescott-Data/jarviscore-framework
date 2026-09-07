from typing import Any, Dict, List, Optional

async def safaricom_mpesa_create_order(payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Initiate STK Push payment (Lipa Na M-Pesa Online). Official: https://developer.safaricom.co.ke/"""
    try:
        if not isinstance(payload, dict) or not payload:
            return _mp_provision({}, 400, 'payload is required')
        body_payload, err = _mp_stk_fields(payload)
        if err:
            return _mp_provision({}, 400, err)
        if not body_payload.get('CallBackURL'):
            return _mp_provision({}, 400, 'CallBackURL or auth_info.callback_url is required')
        if body_payload.get('Amount', 0) <= 0:
            return _mp_provision({}, 400, 'Amount is required')
        if not body_payload.get('PhoneNumber'):
            return _mp_provision({}, 400, 'PhoneNumber is required')
        resp, body, status, msg = await _mp_post('/mpesa/stkpush/v1/processrequest', base_url, body_payload, timeout, verify_ssl)
        if status >= 400:
            return _mp_provision(body if isinstance(body, dict) else {}, status, msg)
        return _mp_provision(body if isinstance(body, dict) else {}, status, 'ok')
    except Exception as e:
        return _mp_provision({}, 500, str(e))

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

def _mp_phone(value):
    digits = ''.join((ch for ch in str(value or '') if ch.isdigit()))
    if digits.startswith('0') and len(digits) == 10:
        return '254' + digits[1:]
    if digits.startswith('254'):
        return digits
    if len(digits) == 9:
        return '254' + digits
    return digits

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

def _mp_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get('CheckoutRequestID') or obj.get('MerchantRequestID') or obj.get('ConversationID') or fallback_id
    ids = [pid] if pid not in (None, '') else []
    rec = obj if obj else {'CheckoutRequestID': pid} if ids else {}
    return {'records': [rec] if rec else [], 'data_count': 1 if rec else 0, 'status': status, 'message': msg, 'provision_ids': ids}

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

def _mp_stk_fields(payload):
    payload = payload if isinstance(payload, dict) else {}
    shortcode = payload.get('BusinessShortCode') or None or None
    passkey = payload.get('Passkey') or None or None
    if not shortcode or not passkey:
        return (None, 'business_short_code and passkey are required')
    ts = payload.get('Timestamp') or _mp_timestamp()
    return ({'BusinessShortCode': str(shortcode), 'Password': payload.get('Password') or _mp_password(shortcode, passkey, ts), 'Timestamp': ts, 'Amount': int(payload.get('Amount') or payload.get('amount') or 0), 'PartyA': _mp_phone(payload.get('PartyA') or payload.get('PhoneNumber') or payload.get('phone_number')), 'PartyB': str(payload.get('PartyB') or shortcode), 'PhoneNumber': _mp_phone(payload.get('PhoneNumber') or payload.get('phone_number') or payload.get('PartyA')), 'AccountReference': str(payload.get('AccountReference') or payload.get('account_reference') or 'order')[:12], 'TransactionDesc': str(payload.get('TransactionDesc') or payload.get('description') or 'Payment')[:13]}, None)
