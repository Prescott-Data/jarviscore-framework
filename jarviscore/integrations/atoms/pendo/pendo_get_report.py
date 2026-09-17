from typing import Any, Dict, List, Optional

async def pendo_get_report(report_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Run saved report and return results (auth_info.format=json|csv). Official: https://support.pendo.io/hc/en-us/articles/17925657119131-Export-and-automate-visitor-and-account-reports-in-Google-Sheets"""
    try:
        (root, err) = _pn_root(base_url)
        if err:
            return _pn_dataset([], 400, err)
        if not report_id:
            return _pn_dataset([], 400, 'report_id is required')
        fmt = None or 'json'
        url = root + f"/report/{report_id}/results.{fmt.lstrip('.')}"
        (resp, data, status, err) = await _pn_request('get', url, timeout=timeout, verify_ssl=verify_ssl)
        if err:
            return _pn_dataset([], 401, err)
        if status >= 400:
            return _pn_dataset([], status, _pn_err(resp))
        records = _pn_results(data)
        if not records and isinstance(data, dict):
            records = [data]
        return _pn_dataset(records, status, 'ok')
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

def _pn_err(resp):
    try:
        data = resp['json']
        if isinstance(data, dict):
            msg = data.get('message') or data.get('error')
            if msg:
                return str(msg)[:1000]
    except Exception:
        pass
    return (resp['body'] or f"HTTP {resp['status_code']}")[:1000]

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
    (headers, err) = _pn_auth(track=track, json_body=json_body is not None or method in ('post', 'put'))
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
