from typing import Any, Dict, List, Optional

async def reddit_ads_search_records(query: str, limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Search campaigns and ads client-side. Official: https://ads-api.reddit.com/docs/v3/"""
    try:
        if not query:
            return _ra_dataset([], 400, 'query is required')
        cap = _ra_cap(limit)
        out = []
        for suffix, rtype in (('/campaigns', 'campaign'), ('/ads', 'ad')):
            if len(out) >= cap:
                break
            rows, status, msg = await _ra_list(base_url, suffix, cap * 2, timeout, verify_ssl)
            if status >= 400 and (not out):
                return _ra_dataset([], status, msg)
            for row in rows:
                if _ra_match(row, query):
                    item = dict(row)
                    item['record_type'] = rtype
                    out.append(item)
                if len(out) >= cap:
                    break
        return _ra_dataset(out[:cap], 200, 'ok')
    except Exception as e:
        return _ra_dataset([], 500, str(e))

def _ra_root(base_url):
    root = (base_url or 'https://ads-api.reddit.com/api/v3').strip().rstrip('/')
    if not root.endswith('/api/v3'):
        if '/api/v3' in root:
            root = root.split('/api/v3')[0] + '/api/v3'
        else:
            root = root + '/api/v3'
    return (root, None)

def _ra_account():
    account_id = None or None or None
    if not account_id:
        return (None, 'auth_info.account_id is required')
    return (str(account_id).strip(), None)

def _ra_auth(json_body=False):
    ua = None or None or 'jarviscoreIntegration/1.0'
    headers = {'Accept': 'application/json', 'User-Agent': str(ua).strip()}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _ra_cap(limit):
    return min(max(int(limit or 25), 1), 100)

def _ra_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _ra_err(resp, body=None):
    if isinstance(body, dict):
        err = body.get('error') or body.get('message')
        if isinstance(err, dict):
            return str(err.get('message') or err)[:1000]
        if err:
            return str(err)[:1000]
    return (resp['body'] if resp is not None else 'request failed')[:1000]

def _ra_rows(body):
    if not isinstance(body, dict):
        return []
    data = body.get('data')
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        return [data]
    return []

async def _ra_request(method, url, params=None, json_body=None, timeout=30, verify_ssl=True):
    headers, err = _ra_auth(json_body=json_body is not None)
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
        return (resp, body, resp['status_code'], _ra_err(resp, body))
    return (resp, body, resp['status_code'], 'ok')

def _ra_account_path(base_url, suffix):
    root, err = _ra_root(base_url)
    if err:
        return (None, err)
    account_id, err = _ra_account()
    if err:
        return (None, err)
    suffix = suffix if suffix.startswith('/') else '/' + suffix
    return (root + '/ad_accounts/' + account_id + suffix, None)

async def _ra_list(base_url, suffix, limit, timeout, verify_ssl, params=None):
    cap = _ra_cap(limit)
    url, err = _ra_account_path(base_url, suffix)
    if err:
        return ([], 400, err)
    records = []
    next_url = None
    status = 200
    msg = 'ok'
    while len(records) < cap:
        if next_url:
            resp, body, status, msg = await _ra_request('get', next_url, timeout=timeout, verify_ssl=verify_ssl)
        else:
            req_params = dict(params or {})
            req_params.setdefault('page.size', min(100, cap))
            resp, body, status, msg = await _ra_request('get', url, params=req_params, timeout=timeout, verify_ssl=verify_ssl)
        if status >= 400:
            return (records, status, msg)
        batch = _ra_rows(body)
        if not batch:
            break
        records.extend(batch)
        pag = body.get('pagination') if isinstance(body, dict) else {}
        next_url = pag.get('next_url') if isinstance(pag, dict) else None
        if not next_url or len(batch) < 1:
            break
    return (records[:cap], status, msg)

def _ra_match(record, query):
    q = str(query).lower()
    for key in ('id', 'name', 'campaign_id', 'ad_group_id', 'configured_status', 'objective'):
        val = record.get(key)
        if val is not None and q in str(val).lower():
            return True
    return False
