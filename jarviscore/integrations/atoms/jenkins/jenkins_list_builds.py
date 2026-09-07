from typing import Any, Dict, List, Optional

async def jenkins_list_builds(job_name: str, limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """List builds for a Jenkins job. Official: https://www.jenkins.io/doc/book/using/remote-access-api/"""
    try:
        base, err = _jk_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        path, perr = _jk_job_path(job_name)
        if perr:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': perr}
        basic, auth_err = _jk_auth()
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        resp = await _jk_get(f'{base}{path}/api/json', basic, {'tree': 'builds[number,url,result,timestamp]'}, timeout, verify_ssl)
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': resp['body'][:1000]}
        records = _jk_builds(resp['json'] if resp['body'] else {})[:limit]
        return {'records': records, 'data_count': len(records), 'status': resp['status_code'], 'message': 'ok'}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _jk_root(base_url):
    root = (base_url or '').rstrip('/')
    if not root:
        return (None, 'base_url is required (https://jenkins.example.com)')
    return (root, None)

def _jk_auth():
    return (None, None)

def _jk_job_path(job_name):
    parts = [p for p in str(job_name or '').split('/') if p]
    if not parts:
        return (None, 'job_name is required')
    return (''.join((f'/job/{p}' for p in parts)), None)

async def _jk_get(url, basic, params, timeout, verify_ssl):
    return await nexus_call('GET', url, params=params)

def _jk_builds(data):
    if isinstance(data, dict):
        builds = data.get('builds')
        if isinstance(builds, list):
            return builds
    return []
