from typing import Any, Dict, List, Optional

async def reddit_ads_get_campaign(campaign_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Get a campaign by ID. Official: https://ads-api.reddit.com/docs/v3/"""
    try:
        if not campaign_id:
            return _ra_dataset([], 400, 'campaign_id is required')
        url, err = _ra_account_path(base_url, '/campaigns/' + str(campaign_id))
        if err:
            return _ra_dataset([], 400, err)
        resp, body, status, msg = await _ra_request('get', url, timeout=timeout, verify_ssl=verify_ssl)
        if status >= 400:
            return _ra_dataset([], status, msg)
        obj = _ra_entity(body)
        return _ra_dataset([obj] if obj else [], status, msg)
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

def _ra_entity(body):
    rows = _ra_rows(body)
    if rows:
        return rows[0]
    if isinstance(body, dict) and isinstance(body.get('data'), dict):
        return body['data']
    return None

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
