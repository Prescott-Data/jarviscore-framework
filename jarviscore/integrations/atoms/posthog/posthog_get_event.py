from typing import Any, Dict, List, Optional

async def posthog_get_event(event_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Retrieve single event by UUID (legacy events endpoint). Official: https://posthog.com/docs/api/events"""
    try:
        if not event_id:
            return _pg_dataset([], 400, 'event_id is required')
        project_id = _pg_project_id()
        if not project_id:
            return _pg_dataset([], 400, 'auth_info.project_id is required')
        host = _pg_app_host(base_url)
        resp, body, status, msg = await _pg_request('get', host + f'/api/projects/{project_id}/events/{str(event_id).strip()}/', timeout=timeout, verify_ssl=verify_ssl)
        if status >= 400:
            return _pg_dataset([], status, msg)
        return _pg_dataset(_pg_items(body), status, msg)
    except Exception as e:
        return _pg_dataset([], 500, str(e))

def _pg_app_host(base_url):
    host = (base_url or None or None or 'https://us.posthog.com').strip().rstrip('/')
    if host.endswith('/api'):
        host = host[:-4]
    return host.rstrip('/')

def _pg_project_id():
    return None or None

def _pg_private_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _pg_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _pg_err(resp, body=None):
    if isinstance(body, dict):
        err = body.get('detail') or body.get('error') or body.get('message')
        if err:
            return str(err)[:1000]
    return (resp['body'] if resp is not None else 'request failed')[:1000]

def _pg_items(data):
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        if isinstance(data.get('results'), list):
            return [x for x in data['results'] if isinstance(x, dict)]
        inner = data.get('result')
        if isinstance(inner, list):
            return [x for x in inner if isinstance(x, dict)]
        if isinstance(inner, dict):
            rows = inner.get('results') or inner.get('rows')
            if isinstance(rows, list):
                return [x for x in rows if isinstance(x, dict)]
        return [data]
    return []

async def _pg_request(method, url, params=None, json_body=None, timeout=30, verify_ssl=True, private=True):
    if private:
        headers, err = _pg_private_auth(json_body=json_body is not None)
    else:
        headers = {'Accept': 'application/json'}
        if json_body is not None:
            headers['Content-Type'] = 'application/json'
        err = None
    if err:
        return (None, None, 401, err)
    kwargs = {'headers': headers, 'timeout': timeout, 'verify': verify_ssl}
    if method == 'get':
        resp = await nexus_call('GET', url, params=params)
    elif method == 'post':
        resp = await nexus_call('POST', url, params=params, json=json_body)
    elif method == 'patch':
        resp = await nexus_call('PATCH', url, params=params, json=json_body)
    else:
        return (None, None, 400, f'unsupported method {method}')
    try:
        body = resp['json'] if resp['content'] else {}
    except Exception:
        body = {}
    if resp['status_code'] >= 400:
        return (resp, body, resp['status_code'], _pg_err(resp, body))
    return (resp, body, resp['status_code'], 'ok')
