from typing import Any, Dict, List, Optional
_TR_ROOT = 'https://api.travis-ci.com'

async def travis_ci_search_records(query: str, limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Travis CI API v3: search records. Official: https://developer.travis-ci.com/resource"""
    try:
        root, err = _tr_root(base_url)
        if err:
            return _tr_dataset([], 400, err)
        if not query:
            return _tr_dataset([], 400, 'query is required')
        headers, aerr = _tr_auth()
        if aerr:
            return _tr_dataset([], 401, aerr)
        resp = await nexus_call('GET', f'{root}/repos', headers=headers, params={'limit': 100})
        if resp['status_code'] >= 400:
            return _tr_dataset([], resp['status_code'], _tr_err(resp))
        data = resp['json'] if resp['content'] else {}
        repos = data.get('repositories') if isinstance(data, dict) else []
        q = query.lower()
        matched = [r for r in repos if isinstance(r, dict) and q in str(r.get('slug', '')).lower()]
        return _tr_dataset(matched[:limit], resp['status_code'], 'ok')
    except Exception as e:
        return _tr_dataset([], 500, str(e))

def _tr_root(base_url):
    root = (base_url or None or _TR_ROOT).strip().rstrip('/')
    return (root, None)

def _tr_auth():
    return ({'Accept': 'application/json', 'Travis-API-Version': '3'}, None)

def _tr_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _tr_err(resp):
    return (resp['body'] or f'HTTP {resp['status_code']}')[:1000]
