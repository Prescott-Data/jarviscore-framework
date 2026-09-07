from typing import Any, Dict, List, Optional

async def segment_list_destinations(limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Segment Public API: list destinations. Official: https://segment.com/docs/api/public-api/#tag/Destinations/operation/listDestinations"""
    try:
        root, _ = _sg_root(base_url)
        records, status, msg = await _sg_paginate(root + '/destinations', 'destinations', limit, timeout, verify_ssl)
        return _sg_dataset(records, status, msg)
    except Exception as e:
        return _sg_dataset([], 500, str(e))

def _sg_root(base_url):
    root = (base_url or None or None or 'https://api.segmentapis.com').strip().rstrip('/')
    if root.endswith('/v1'):
        root = root[:-3].rstrip('/')
    return (root, None)

def _sg_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _sg_cap(limit):
    return min(max(int(limit or 25), 1), 200)

def _sg_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _sg_err(resp):
    try:
        data = resp['json']
        if isinstance(data, dict):
            msg = data.get('message') or data.get('error')
            if msg:
                return str(msg)[:1000]
    except Exception:
        pass
    return (resp['body'] or f'HTTP {resp['status_code']}')[:1000]

def _sg_items(data, key):
    if isinstance(data, dict):
        block = data.get('data')
        if isinstance(block, dict):
            items = block.get(key)
            if isinstance(items, list):
                return [x for x in items if isinstance(x, dict)]
        items = data.get(key)
        if isinstance(items, list):
            return [x for x in items if isinstance(x, dict)]
    return []

async def _sg_paginate(url, collection_key, limit, timeout, verify_ssl):
    cap = _sg_cap(limit)
    records = []
    status = 200
    pages = 0
    next_url = url
    params = {'pagination[count]': min(cap, 200)}
    while len(records) < cap and pages < 50:
        pages += 1
        headers, err = _sg_auth()
        if err:
            return (records, 401, err)
        resp = await nexus_call('GET', next_url, headers=headers, params=params if pages == 1 else None)
        try:
            data = resp['json'] if resp['content'] else {}
        except Exception:
            data = {}
        status = resp['status_code']
        if status >= 400:
            return (records, status, _sg_err(resp))
        batch = _sg_items(data, collection_key)
        records.extend(batch)
        pagination = data.get('pagination') if isinstance(data, dict) else {}
        nxt = pagination.get('next') if isinstance(pagination, dict) else None
        if not nxt or not batch:
            break
        next_url = nxt if str(nxt).startswith('http') else url
        params = None
    return (records[:cap], status, 'ok')
