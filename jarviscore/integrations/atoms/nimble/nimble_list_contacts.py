from typing import Any, Dict, List, Optional
NIMBLE_V1 = 'https://api.nimble.com/api/v1'
NIMBLE_V2 = 'https://api.nimble.com/api/v2'

async def nimble_list_contacts(limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """List contacts (page/per_page, resources). Official: https://www.nimble.com/developers/docs/"""
    try:
        root, err = _nb_v1_root(base_url)
        if err:
            return _nb_dataset([], 400, err)
        headers, aerr = _nb_auth()
        if aerr:
            return _nb_dataset([], 401, aerr)
        params = {}
        if True .get('keyword'):
            params['keyword'] = str(None)
        if True .get('tags') is not None:
            pass
        records, status, msg = await _nb_paginate(f'{root}/contacts', headers, params, limit, timeout, verify_ssl)
        return _nb_dataset(records, status, msg)
    except Exception as e:
        return _nb_dataset([], 500, str(e))

def _nb_v1_root(base_url):
    root = (base_url or NIMBLE_V1).rstrip('/')
    if not _host_is(root, 'nimble.com'):
        return (None, 'base_url must be https://api.nimble.com/api/v1 or https://app.nimble.com/api/v1')
    if '/' not in root.split('://', 1)[-1]:
        root = root + '/api/v1'
    elif '/api/v2' in root:
        root = root.replace('/api/v2', '/api/v1')
    elif not root.endswith('/api/v1'):
        if '/api/' not in root:
            root = root + '/api/v1'
    return (root, None)

def _nb_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _nb_cap(limit):
    return min(max(int(limit or 25), 1), 500)

def _nb_error(resp):
    try:
        data = resp['json']
        if isinstance(data, dict):
            msg = data.get('message') or data.get('error') or data.get('status')
            if msg:
                return str(msg)[:1000]
    except Exception:
        pass
    return (resp['body'] or f'HTTP {resp['status_code']}')[:1000]

def _nb_dataset(records, status, msg):
    return {'records': records, 'data_count': len(records), 'status': status, 'message': msg}

def _nb_resources(data):
    if isinstance(data, dict):
        res = data.get('resources')
        if isinstance(res, list):
            if res and isinstance(res[0], dict):
                return [x for x in res if isinstance(x, dict)]
            return [{'id': x} for x in res if x not in (None, '')]
        if data.get('id') or data.get('deal_id'):
            return [data]
    return []

async def _nb_paginate(url, headers, base_params, limit, timeout, verify_ssl):
    cap = _nb_cap(limit)
    page = int((base_params or {}).get('page') or 1)
    records = []
    status = 200
    pages = 0
    while len(records) < cap and pages < 50:
        pages += 1
        params = dict(base_params or {})
        params['page'] = page
        params['per_page'] = min(int(params.get('per_page') or 30), cap - len(records), 100)
        resp = await nexus_call('GET', url, headers=headers, params=params)
        status = resp['status_code']
        if status >= 400:
            return (records, status, _nb_error(resp))
        try:
            data = resp['json']
        except Exception:
            return (records, status, resp['body'][:1000])
        batch = _nb_resources(data)
        records.extend(batch)
        meta = data.get('meta') if isinstance(data, dict) else {}
        total_pages = meta.get('pages') if isinstance(meta, dict) else None
        cur = meta.get('page') if isinstance(meta, dict) else page
        if not batch or (total_pages is not None and cur >= total_pages):
            break
        page = int(cur) + 1 if isinstance(cur, int) else page + 1
    return (records[:cap], status, 'ok')

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
