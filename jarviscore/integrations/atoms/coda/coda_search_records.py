from typing import Any, Dict, List, Optional
CODA_API = 'https://coda.io/apis/v1'

async def coda_search_records(query: str, limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Search Coda docs by name or id (client filter on GET /docs). Bearer API token in Authorization header. Official: https://coda.io/apis/v1"""
    try:
        if not query:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'query is required'}
        api = _coda_api_root(base_url)
        (headers, auth_err) = _coda_auth()
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        fetch_limit = max(limit * 4, limit, 25)
        (records, status, msg) = await _coda_paginate(f'{api}/docs', headers, fetch_limit, timeout, verify_ssl)
        if status >= 400:
            return {'records': [], 'data_count': 0, 'status': status, 'message': msg}
        filtered = _coda_filter_docs(records, query)[:limit]
        return {'records': filtered, 'data_count': len(filtered), 'status': status, 'message': 'ok'}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _coda_api_root(base_url):
    root = (base_url or CODA_API).rstrip('/')
    if _host_is(root, 'coda.io') and '/apis/v1' not in root:
        if root.endswith('/apis'):
            root = root + '/v1'
        else:
            root = root + '/apis/v1'
    return root

def _coda_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (None, 'auth_info requires api_key or access_token (Bearer)')

async def _coda_get(url, headers, params, timeout, verify_ssl):
    return await nexus_call('GET', url, headers=headers, params=params)

def _coda_items(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        items = data.get('items')
        if isinstance(items, list):
            return items
    return []

async def _coda_paginate(url, headers, limit, timeout, verify_ssl):
    records = []
    page_token = None
    status = 0
    page_size = min(max(int(limit or 25), 1), 100)
    while len(records) < limit:
        params = {'pageSize': min(page_size, limit - len(records))}
        if page_token:
            params['pageToken'] = page_token
        resp = await _coda_get(url, headers, params, timeout, verify_ssl)
        status = resp['status_code']
        if status >= 400:
            return (records, status, resp['body'][:1000])
        data = resp['json'] if resp['body'] else {}
        batch = _coda_items(data)
        for item in batch:
            if isinstance(item, dict):
                records.append(item)
                if len(records) >= limit:
                    break
        page_token = data.get('nextPageToken') if isinstance(data, dict) else None
        if not batch or not page_token:
            break
    return (records[:limit], status, 'ok')

def _coda_filter_docs(docs, query):
    q = (query or '').strip().lower()
    if not q:
        return docs
    out = []
    for row in docs:
        if not isinstance(row, dict):
            continue
        name = str(row.get('name') or row.get('title') or '').lower()
        did = str(row.get('id') or row.get('docId') or '').lower()
        if q in name or q == did:
            out.append(row)
    return out

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
