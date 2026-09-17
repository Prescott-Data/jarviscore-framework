from typing import Any, Dict, List, Optional

async def teamcity_list_builds(limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """TeamCity REST: list builds. Official: https://www.jetbrains.com/help/teamcity/rest/teamcity-rest.html"""
    try:
        (root, err) = _tc_root(base_url)
        if err:
            return _tc_dataset([], 400, err)
        (headers, aerr) = _tc_auth()
        if aerr:
            return _tc_dataset([], 401, aerr)
        resp = await nexus_call('GET', f'{root}/builds', headers=headers, params={'locator': f'count:{limit}'})
        if resp['status_code'] >= 400:
            return _tc_dataset([], resp['status_code'], _tc_err(resp))
        data = resp['json'] if resp['content'] else {}
        return _tc_dataset(_tc_items(data, 'build'), resp['status_code'], 'ok')
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
    return (resp['body'] or f"HTTP {resp['status_code']}")[:1000]

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
