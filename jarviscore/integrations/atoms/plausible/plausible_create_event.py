from typing import Any, Dict, List, Optional

async def plausible_create_event(payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Record pageview/custom event via Events API. Official: https://plausible.io/docs/events-api"""
    try:
        if not isinstance(payload, dict) or not payload:
            return _pl_provision({}, 400, 'payload is required')
        host = _pl_host(base_url)
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
        ua = None or payload.get('user_agent')
        if ua:
            headers['User-Agent'] = str(ua)
        xff = None or payload.get('x_forwarded_for')
        if xff:
            headers['X-Forwarded-For'] = str(xff)
        token = _pl_stats_token()
        if token:
            t = str(token).strip()
            headers['Authorization'] = t if t.lower().startswith('bearer ') else f'Bearer {t}'
        resp = await nexus_call('POST', host + '/api/event', headers=headers, json=payload)
        status = resp['status_code']
        try:
            body = resp['json'] if resp['content'] else {}
        except Exception:
            body = {}
        if status >= 400:
            return _pl_provision(body if isinstance(body, dict) else {}, status, _pl_err(resp, body))
        name = payload.get('name')
        rec = {'name': name, 'domain': payload.get('domain'), 'url': payload.get('url')}
        if resp['headers'].get('x-plausible-dropped') == '1':
            return _pl_provision(rec, 400, 'event dropped by Plausible bot filtering')
        return _pl_provision(rec, status, 'ok', fallback_id=name)
    except Exception as e:
        return _pl_provision({}, 500, str(e))

def _pl_host(base_url):
    host = (base_url or None or None or 'https://plausible.io').strip().rstrip('/')
    if host.endswith('/api'):
        host = host[:-4]
    return host.rstrip('/') or 'https://plausible.io'

def _pl_stats_token():
    return None or None

def _pl_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get('id') or obj.get('name') or fallback_id
    ids = [pid] if pid not in (None, '') else []
    rec = obj if obj else {'id': pid, 'name': pid} if ids else {}
    return {'records': [rec] if rec else [], 'data_count': 1 if rec else 0, 'status': status, 'message': msg, 'provision_ids': ids}

def _pl_err(resp, body=None):
    if isinstance(body, dict):
        err = body.get('error') or body.get('message')
        if err:
            return str(err)[:1000]
    return (resp['body'] if resp is not None else 'request failed')[:1000]
