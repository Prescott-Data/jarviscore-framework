from typing import Any, Dict, List, Optional

async def wrike_search_records(query: str, limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """wrike REST: search records. Official: https://developers.wrike.com/api/v4/"""
    try:
        root, err = _root(base_url)
        if err:
            return _dataset([], 400, err)
        if not query:
            return _dataset([], 400, 'query is required')
        headers, aerr = _auth()
        if aerr:
            return _dataset([], 401, aerr)
        resp = await nexus_call('GET', root + '/tasks', headers=headers, params={'title': query})
        if resp['status_code'] >= 400:
            return _dataset([], resp['status_code'], _err(resp))
        data = resp['json'] if resp['content'] else {}
        if isinstance(data, dict) and 'data' in data:
            records = data['data'] if isinstance(data['data'], list) else [data['data']]
        elif isinstance(data, list):
            records = data
        else:
            records = [data] if isinstance(data, dict) else []
        return _dataset(records, resp['status_code'], 'ok')
    except Exception as e:
        return _dataset([], 500, str(e))

def _root(base_url):
    root = (base_url or None or 'https://www.wrike.com/api/v4').strip().rstrip('/')
    if not root:
        return (None, 'base_url is required')
    return (root, None)

def _auth():
    return ({'Accept': 'application/json'}, None)

def _dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _err(resp):
    return (resp['body'] or f'HTTP {resp['status_code']}')[:1000]
