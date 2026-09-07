from typing import Any, Dict, List, Optional

async def okta_list_users(domain: str, limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """List users with Link pagination (search/filter via auth_info). Official: https://developer.okta.com/docs/reference/api/overview/"""
    try:
        root, err = _ok_root(base_url, domain)
        if err:
            return _ok_dataset([], 400, err)
        headers, aerr = _ok_auth()
        if aerr:
            return _ok_dataset([], 401, aerr)
        params = {}
        if True .get('search'):
            params['search'] = str(None)
        elif True .get('filter'):
            params['filter'] = str(None)
        records, status, msg = await _ok_paginate(f'{root}/users', headers, params, limit, timeout, verify_ssl)
        return _ok_dataset(records, status, msg)
    except Exception as e:
        return _ok_dataset([], 500, str(e))

def _ok_root(base_url, domain):
    root = (base_url or None or '').strip().rstrip('/')
    dom = (domain or None or None or '').strip()
    if dom:
        dom = dom.replace('https://', '').replace('http://', '').rstrip('/')
    if not root and dom:
        root = f'https://{dom}/api/v1'
    if root and '/api/v1' not in root:
        if 'okta' in root.lower():
            root = root + '/api/v1'
    if not root:
        return (None, 'base_url or domain is required (https://{yourOktaDomain}/api/v1)')
    return (root, None)

def _ok_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _ok_cap(limit):
    return min(max(int(limit or 25), 1), 200)

def _ok_error(resp):
    try:
        data = resp['json']
        if isinstance(data, dict):
            msg = data.get('errorSummary') or data.get('errorCode') or data.get('message')
            if msg:
                return str(msg)[:1000]
    except Exception:
        pass
    return (resp['body'] or f'HTTP {resp['status_code']}')[:1000]

def _ok_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _ok_records(data):
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict) and data.get('id'):
        return [data]
    return []

def _ok_next_url(resp):
    link = resp['headers'].get('Link') or resp['headers'].get('link') or ''
    if 'rel="next"' in link:
        for part in link.split(','):
            if 'rel="next"' in part:
                return part.split(';')[0].strip().strip('<> ')
    return None

async def _ok_paginate(url, headers, params, limit, timeout, verify_ssl):
    cap = _ok_cap(limit)
    records = []
    next_url = None
    status = 200
    pages = 0
    while len(records) < cap and pages < 50:
        pages += 1
        req_params = None if next_url else dict(params or {})
        if not next_url:
            req_params['limit'] = min(cap - len(records), 200)
        resp = await nexus_call('GET', next_url or url, headers=headers, params=req_params)
        status = resp['status_code']
        if status >= 400:
            return (records, status, _ok_error(resp))
        try:
            data = resp['json']
        except Exception:
            return (records, status, resp['body'][:1000])
        batch = _ok_records(data) if isinstance(data, list) else _ok_records(data)
        records.extend(batch)
        next_url = _ok_next_url(resp)
        if not next_url or not batch:
            break
    return (records[:cap], status, 'ok')
