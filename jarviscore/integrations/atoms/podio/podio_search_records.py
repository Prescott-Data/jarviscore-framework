from typing import Any, Dict, List, Optional

async def podio_search_records(query: str, limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Search items/tasks in space or app. Official: https://developers.podio.com/doc/search"""
    try:
        if not query:
            return _po_dataset([], 400, 'query is required')
        (root, err) = _po_root(base_url)
        if err:
            return _po_dataset([], 400, err)
        app_id = None or None
        space_id = None or None
        cap = _po_cap(limit)
        records = []
        offset = 0
        status = 200
        msg = 'ok'
        if app_id:
            path = '/search/app/' + str(app_id).strip() + '/'
        elif space_id:
            path = '/search/space/' + str(space_id).strip() + '/'
        else:
            path = '/search/v2/'
        while len(records) < cap:
            body = {'query': str(query), 'limit': min(20, cap - len(records)), 'offset': offset}
            (resp, data, status, msg) = await _po_request('post', root + path, json_body=body, timeout=timeout, verify_ssl=verify_ssl)
            if status >= 400:
                return _po_dataset(records[:cap], status, msg)
            batch = _po_items(data)
            records.extend(batch)
            if len(batch) < body['limit']:
                break
            offset += len(batch)
        return _po_dataset(records[:cap], status, msg)
    except Exception as e:
        return _po_dataset([], 500, str(e))

def _po_root(base_url):
    root = (base_url or None or None or 'https://api.podio.com').strip().rstrip('/')
    return (root, None)

def _po_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _po_cap(limit):
    return min(max(int(limit or 25), 1), 500)

def _po_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _po_err(resp, body=None):
    if isinstance(body, dict):
        err = body.get('error_description') or body.get('error')
        if err:
            return str(err)[:1000]
    return (resp['body'] if resp is not None else 'request failed')[:1000]

def _po_items(data):
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ('items', 'tasks', 'results'):
            val = data.get(key)
            if isinstance(val, list):
                return [x for x in val if isinstance(x, dict)]
        return [data]
    return []

async def _po_request(method, url, params=None, json_body=None, timeout=30, verify_ssl=True):
    (headers, err) = _po_auth(json_body=json_body is not None)
    if err:
        return (None, None, 401, err)
    kwargs = {'headers': headers, 'timeout': timeout, 'verify': verify_ssl}
    if method == 'get':
        resp = await nexus_call('GET', url, params=params)
    elif method == 'post':
        resp = await nexus_call('POST', url, params=params, json=json_body)
    elif method == 'put':
        resp = await nexus_call('PUT', url, params=params, json=json_body)
    else:
        return (None, None, 400, f'unsupported method {method}')
    try:
        body = resp['json'] if resp['content'] else {}
    except Exception:
        body = {}
    if resp['status_code'] >= 400:
        return (resp, body, resp['status_code'], _po_err(resp, body))
    return (resp, body, resp['status_code'], 'ok')
