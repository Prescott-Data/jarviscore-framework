from typing import Any, Dict, List, Optional

async def pendo_list_events(limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """List track event types via Aggregation API trackTypes source. Official: https://engageapi.pendo.io/ and https://www.pendo.io/pendo-blog/pendo-aggs-writing-your-first-aggregation/"""
    try:
        cap = _pn_cap(limit)
        pipeline = [{}, {'limit': cap}]
        records, status, msg = await _pn_aggregate(pipeline, request_id='list-track-types', timeout=timeout, verify_ssl=verify_ssl)
        return _pn_dataset(records[:cap], status, msg)
    except Exception as e:
        return _pn_dataset([], 500, str(e))

def _pn_root(base_url):
    root = (base_url or None or None or 'https://app.pendo.io/api/v1').strip().rstrip('/')
    if '/api/v1' not in root:
        if root.endswith('/api'):
            root = root + '/v1'
        elif _host_is(root, 'pendo.io'):
            root = root + '/api/v1'
    if not root:
        return (None, 'base_url is required (https://app.pendo.io/api/v1)')
    return (root, None)

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

def _pn_cap(limit):
    return min(max(int(limit or 25), 1), 100000)

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

def _pn_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _pn_results(data):
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ('results', 'data', 'rows', 'reports'):
            items = data.get(key)
            if isinstance(items, list):
                return [x for x in items if isinstance(x, dict)]
        if data.get('id'):
            return [data]
    return []

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

async def _pn_aggregate(pipeline, request_id='pendo-query', timeout=30, verify_ssl=True):
    root, err = _pn_root(None)
    if err:
        return ([], 400, err)
    body = {'response': {'mimeType': 'application/json'}, 'request': {'requestId': request_id, 'name': request_id, 'pipeline': pipeline}}
    resp, data, status, err = await _pn_request('post', root + '/aggregation', json_body=body, timeout=timeout, verify_ssl=verify_ssl)
    if err:
        return ([], 401, err)
    if status >= 400:
        return ([], status, _pn_err(resp))
    return (_pn_results(data), status, 'ok')

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
