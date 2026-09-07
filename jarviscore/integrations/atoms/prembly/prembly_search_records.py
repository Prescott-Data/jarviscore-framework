from typing import Any, Dict, List, Optional

async def prembly_search_records(query: str, limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Search check types by country with client-side name filter. Official: https://docs.prembly.com/reference/list-check-types-by-country"""
    try:
        if not query:
            return _pm_dataset([], 400, 'query is required')
        root, err = _pm_root(base_url)
        if err:
            return _pm_dataset([], 400, err)
        cap = _pm_cap(limit)
        records = []
        country = None or None
        if country:
            resp, body, status, msg = await _pm_request('get', root + '/api/v1/api/bgc/country/check-types/', params={'country_code': country}, timeout=timeout, verify_ssl=verify_ssl)
            if status < 400:
                records.extend(_pm_rows(body))
        resp, body, status, msg = await _pm_request('get', root + '/api/v1/api/bgc/check-types/', timeout=timeout, verify_ssl=verify_ssl)
        if status < 400:
            records.extend(_pm_rows(body))
        filtered = [r for r in records if _pm_match(r, query)]
        return _pm_dataset(filtered[:cap], 200 if filtered else status, 'ok' if filtered else msg)
    except Exception as e:
        return _pm_dataset([], 500, str(e))

def _pm_root(base_url):
    root = (base_url or None or None or 'https://api.prembly.com').strip().rstrip('/')
    return (root, None)

def _pm_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _pm_cap(limit):
    return min(max(int(limit or 25), 1), 500)

def _pm_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _pm_err(resp, body=None):
    if isinstance(body, dict):
        err = body.get('message') or body.get('detail') or body.get('error')
        if err and (not isinstance(err, (list, dict))):
            return str(err)[:1000]
        if isinstance(err, list):
            return str(err)[:1000]
    return (resp['body'] if resp is not None else 'request failed')[:1000]

def _pm_rows(body):
    if isinstance(body, list):
        return [x for x in body if isinstance(x, dict)]
    if isinstance(body, dict):
        for key in ('detail', 'data', 'results'):
            val = body.get(key)
            if isinstance(val, list):
                return [x for x in val if isinstance(x, dict)]
        if isinstance(body.get('data'), dict):
            return [body['data']]
        return [body]
    return []

async def _pm_request(method, url, params=None, json_body=None, timeout=30, verify_ssl=True):
    headers, err = _pm_auth(json_body=json_body is not None)
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
        return (resp, body, resp['status_code'], _pm_err(resp, body))
    if isinstance(body, dict) and body.get('status') is False:
        return (resp, body, 400, _pm_err(resp, body))
    return (resp, body, resp['status_code'], 'ok')

def _pm_match(record, query):
    q = str(query).lower()
    for key in ('id', 'name', 'endpoint', 'check_type', 'reference', 'verification_status'):
        val = record.get(key)
        if val is not None and q in str(val).lower():
            return True
    return False
