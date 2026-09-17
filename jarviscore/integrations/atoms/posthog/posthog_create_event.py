from typing import Any, Dict, List, Optional

async def posthog_create_event(payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Capture event via public ingest API (project api_key). Official: https://posthog.com/docs/api/capture"""
    try:
        if not isinstance(payload, dict) or not payload:
            return _pg_provision({}, 400, 'payload is required')
        body = dict(payload)
        if 'api_key' not in body:
            api_key = None or None or None
            if api_key:
                body['api_key'] = api_key
        if not body.get('api_key'):
            return _pg_provision({}, 400, 'payload.api_key or auth_info.project_api_key is required')
        if not body.get('event'):
            return _pg_provision({}, 400, 'payload.event is required')
        if not body.get('distinct_id'):
            return _pg_provision({}, 400, 'payload.distinct_id is required')
        ingest = _pg_ingest_host(base_url)
        resp = await nexus_call('POST', ingest + '/i/v0/e/', json=body)
        status = resp['status_code']
        try:
            data = resp['json'] if resp['content'] else {}
        except Exception:
            data = {}
        if status >= 400:
            return _pg_provision(data if isinstance(data, dict) else {}, status, _pg_err(resp, data))
        rec = {'event': body.get('event'), 'distinct_id': body.get('distinct_id')}
        return _pg_provision(rec, status, 'ok', fallback_id=body.get('event'))
    except Exception as e:
        return _pg_provision({}, 500, str(e))

def _pg_app_host(base_url):
    host = (base_url or None or None or 'https://us.posthog.com').strip().rstrip('/')
    if host.endswith('/api'):
        host = host[:-4]
    return host.rstrip('/')

def _pg_ingest_host(base_url):
    ingest = None or None
    if ingest:
        return str(ingest).strip().rstrip('/')
    app = _pg_app_host(base_url)
    if _host_is(app, 'eu.posthog.com'):
        return 'https://eu.i.posthog.com'
    if _host_is(app, 'posthog.com'):
        return 'https://us.i.posthog.com'
    return app

def _pg_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get('id') or obj.get('uuid') or obj.get('short_id') or fallback_id
    ids = [pid] if pid not in (None, '') else []
    rec = obj if obj else {'id': pid} if ids else {}
    return {'records': [rec] if rec else [], 'data_count': 1 if rec else 0, 'status': status, 'message': msg, 'provision_ids': ids}

def _pg_err(resp, body=None):
    if isinstance(body, dict):
        err = body.get('detail') or body.get('error') or body.get('message')
        if err:
            return str(err)[:1000]
    return (resp['body'] if resp is not None else 'request failed')[:1000]

def _host_is(url, *domains):
    """True only if url's hostname equals or is a subdomain of one of domains."""
    from urllib.parse import urlparse
    u = str(url or '').strip()
    if '://' not in u:
        u = 'https://' + u
    try:
        host = (urlparse(u).hostname or '').lower()
    except Exception:
        return False
    return any((host == d or host.endswith('.' + d) for d in domains))
