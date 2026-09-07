from typing import Any, Dict, List, Optional

async def sourceforge_list_projects(username: str, limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """SourceForge REST: list user projects. Official: https://sourceforge.net/p/forge/documentation/REST%20API/"""
    try:
        if not username:
            return _sf_dataset([], 400, 'username is required')
        root, _ = _sf_root(base_url)
        headers, err = _sf_auth()
        if err:
            return _sf_dataset([], 401, err)
        resp = await nexus_call('GET', f'{root}/rest/u/{username}/profile/', headers=headers)
        try:
            data = resp['json'] if resp['content'] else {}
        except Exception:
            data = {}
        if resp['status_code'] >= 400:
            return _sf_dataset([], resp['status_code'], _sf_err(resp))
        projects = data.get('projects') if isinstance(data, dict) else data
        records = [x for x in (projects if isinstance(projects, list) else []) if isinstance(x, dict)][:_sf_cap(limit)]
        return _sf_dataset(records, resp['status_code'], 'ok')
    except Exception as e:
        return _sf_dataset([], 500, str(e))

def _sf_root(base_url):
    root = (base_url or None or None or 'https://sourceforge.net').strip().rstrip('/')
    return (root, None)

def _sf_auth():
    return ({'Accept': 'application/json'}, None)

def _sf_cap(limit):
    return min(max(int(limit or 25), 1), 100)

def _sf_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _sf_err(resp):
    return (resp['body'] or f'HTTP {resp['status_code']}')[:1000]
