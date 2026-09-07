from typing import Any, Dict, List, Optional

async def pagerduty_get_service(service_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Get service by id. Official: https://developer.pagerduty.com/api-reference/operations/getService"""
    try:
        root, err = _pd_root(base_url)
        if err:
            return _pd_dataset([], 400, err)
        if not service_id:
            return _pd_dataset([], 400, 'service_id is required')
        resp, status, err = await _pd_request('get', root + f'/services/{service_id}', timeout=timeout, verify_ssl=verify_ssl)
        if err:
            return _pd_dataset([], 401, err)
        if status >= 400:
            return _pd_dataset([], status, _pd_err(resp))
        try:
            data = resp['json']
        except Exception:
            return _pd_dataset([], status, 'invalid JSON response')
        return _pd_dataset(_pd_single(data, 'service'), status, 'ok')
    except Exception as e:
        return _pd_dataset([], 500, str(e))

def _pd_root(base_url):
    root = (base_url or None or None or 'https://api.pagerduty.com').strip().rstrip('/')
    if not root:
        return (None, 'base_url is required (https://api.pagerduty.com)')
    return (root, None)

def _pd_auth(json_body=False, from_header=False):
    pd_scheme = 'Token {}='.format('tok' + 'en')
    headers = {'Accept': 'application/vnd.pagerduty+json;version=2'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    if from_header:
        frm = None or None
        if frm:
            headers['From'] = str(frm).strip()
    return (headers, None)

def _pd_err(resp):
    try:
        data = resp['json']
        if isinstance(data, dict):
            errs = data.get('errors')
            if isinstance(errs, list) and errs:
                msgs = []
                for e in errs:
                    if isinstance(e, dict):
                        msgs.append(e.get('detail') or e.get('title') or str(e))
                    else:
                        msgs.append(str(e))
                if msgs:
                    return '; '.join(msgs)[:1000]
            msg = data.get('message') or data.get('error')
            if msg:
                return str(msg)[:1000]
    except Exception:
        pass
    return (resp['body'] or f'HTTP {resp['status_code']}')[:1000]

def _pd_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _pd_single(data, key):
    if isinstance(data, dict):
        inner = data.get(key)
        if isinstance(inner, dict):
            return [inner]
        if data.get('id'):
            return [data]
    return []

async def _pd_request(method, url, params=None, json_body=None, timeout=30, verify_ssl=True, from_header=False):
    headers, err = _pd_auth(json_body=json_body is not None, from_header=from_header)
    if err:
        return (None, 401, err)
    kwargs = {'headers': headers, 'timeout': timeout, 'verify': verify_ssl}
    if method == 'get':
        resp = await nexus_call('GET', url, params=params)
    elif method == 'post':
        resp = await nexus_call('POST', url, params=params, json=json_body)
    elif method == 'put':
        resp = await nexus_call('PUT', url, params=params, json=json_body)
    else:
        return (None, 400, f'unsupported method {method}')
    return (resp, resp['status_code'], None)
