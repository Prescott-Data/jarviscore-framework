from typing import Any, Dict, List, Optional

async def teamcity_search_records(query: str, limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """TeamCity REST: search projects. Official: https://www.jetbrains.com/help/teamcity/rest/teamcity-rest.html"""
    try:
        root, err = _tc_root(base_url)
        if err:
            return _tc_dataset([], 400, err)
        if not query:
            return _tc_dataset([], 400, 'query is required')
        headers, aerr = _tc_auth()
        if aerr:
            return _tc_dataset([], 401, aerr)
        resp = await nexus_call('GET', f'{root}/projects', headers=headers, params={'locator': 'count:100'})
        if resp['status_code'] >= 400:
            return _tc_dataset([], resp['status_code'], _tc_err(resp))
        data = resp['json'] if resp['content'] else {}
        records = _tc_items(data, 'project')
        q = query.lower()
        matched = [r for r in records if q in str(r.get('name', '')).lower() or q in str(r.get('id', '')).lower()]
        return _tc_dataset(matched[:limit], resp['status_code'], 'ok')
    except Exception as e:
        return _tc_dataset([], 500, str(e))

def _tc_root(base_url):
    root = (base_url or None or None or '').strip().rstrip('/')
    if not root:
        return (None, 'base_url is required (https://teamcity.example.com)')
    if not root.endswith('/app/rest'):
        root = root + '/app/rest' if '/app/' not in root else root
    return (root, None)

def _tc_auth():
    return ({'Accept': 'application/json'}, None)

def _tc_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _tc_err(resp):
    return (resp['body'] or f'HTTP {resp['status_code']}')[:1000]

def _tc_items(data, key):
    if isinstance(data, dict):
        block = data.get(key) or data.get(key.rstrip('s'))
        if isinstance(block, list):
            return [x for x in block if isinstance(x, dict)]
        if isinstance(block, dict):
            return [block]
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    return []
