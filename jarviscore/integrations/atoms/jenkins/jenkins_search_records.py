from typing import Any, Dict, List, Optional

async def jenkins_search_records(query: str, limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Search Jenkins jobs by name. Official: https://www.jenkins.io/doc/book/using/remote-access-api/"""
    try:
        if not query:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'query is required'}
        base, err = _jk_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        basic, auth_err = _jk_auth()
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        resp = await _jk_get(f'{base}/api/json', basic, {'tree': 'jobs[name,url,color,_class]'}, timeout, verify_ssl)
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': resp['body'][:1000]}
        needle = query.lower()
        matched = [j for j in _jk_jobs(resp['json'] if resp['body'] else {}) if isinstance(j, dict) and needle in str(j.get('name', '')).lower()][:limit]
        return {'records': matched, 'data_count': len(matched), 'status': resp['status_code'], 'message': 'ok'}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _jk_root(base_url):
    root = (base_url or '').rstrip('/')
    if not root:
        return (None, 'base_url is required (https://jenkins.example.com)')
    return (root, None)

def _jk_auth():
    return (None, None)

async def _jk_get(url, basic, params, timeout, verify_ssl):
    return await nexus_call('GET', url, params=params)

def _jk_jobs(data):
    if isinstance(data, dict):
        jobs = data.get('jobs')
        if isinstance(jobs, list):
            return jobs
    return []
