import time
from typing import Any, Dict, List, Optional

async def pendo_create_event(payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Ingest server-side track event (track_event_secret; event + visitorId required). Official: https://support.pendo.io/hc/en-us/articles/360032294291-Configure-Track-Events"""
    try:
        if not isinstance(payload, dict) or not payload:
            return _pn_provision({}, 400, 'payload is required')
        if not payload.get('event'):
            return _pn_provision({}, 400, 'payload.event is required')
        if not payload.get('visitorId'):
            return _pn_provision({}, 400, 'payload.visitorId is required')
        body = dict(payload)
        body.setdefault('type', 'track')
        if 'timestamp' not in body:
            body['timestamp'] = int(time.time() * 1000)
        host = _pn_host(base_url)
        resp, data, status, err = await _pn_request('post', host + '/data/track', json_body=body, timeout=timeout, verify_ssl=verify_ssl, track=True)
        if err:
            return _pn_provision({}, 401, err)
        if status >= 400:
            return _pn_provision(data if isinstance(data, dict) else {}, status, _pn_err(resp))
        ref = body.get('event')
        return _pn_provision({'event': ref, 'visitorId': body.get('visitorId'), 'timestamp': body.get('timestamp')}, status, 'ok', fallback_id=ref)
    except Exception as e:
        return _pn_provision({}, 500, str(e))

def _pn_host(base_url):
    root = (base_url or None or None or 'https://app.pendo.io').strip().rstrip('/')
    if '/api/v1' in root:
        root = root.split('/api/v1')[0]
    return root.rstrip('/') or 'https://app.pendo.io'

def _pn_key(track=False):
    if track:
        return None or None or None
    return None or None

def _pn_auth(track=False, json_body=True):
    key = _pn_key(track=track)
    if not key:
        if track:
            return (None, 'auth_info.track_event_secret is required for track ingest')
        return (None, 'auth_info.integration_key is required')
    headers = {'x-pendo-integration-key': str(key).strip()}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _pn_err(resp):
    try:
        data = resp['json']
        if isinstance(data, dict):
            msg = data.get('message') or data.get('error')
            if msg:
                return str(msg)[:1000]
    except Exception:
        pass
    return (resp['body'] or f'HTTP {resp['status_code']}')[:1000]

def _pn_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get('id') or obj.get('event') or obj.get('reference') or fallback_id
    ids = [pid] if pid not in (None, '') else []
    rec = obj if obj else {'id': pid} if ids else {}
    return {'records': [rec] if rec else [], 'data_count': 1 if rec else 0, 'status': status, 'message': msg, 'provision_ids': ids}

async def _pn_request(method, url, params=None, json_body=None, timeout=30, verify_ssl=True, track=False):
    headers, err = _pn_auth(track=track, json_body=json_body is not None or method in ('post', 'put'))
    if err:
        return (None, None, 401, err)
    kwargs = {'headers': headers, 'timeout': timeout, 'verify': verify_ssl}
    if method == 'get':
        resp = await nexus_call('GET', url, params=params)
    elif method == 'post':
        resp = await nexus_call('POST', url, params=params, json=json_body)
    else:
        return (None, None, 400, f'unsupported method {method}')
    try:
        data = resp['json'] if resp['content'] else {}
    except Exception:
        data = {'raw': resp['body'][:1000]} if resp['content'] else {}
    return (resp, data, resp['status_code'], None)
