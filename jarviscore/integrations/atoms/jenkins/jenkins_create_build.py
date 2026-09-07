from typing import Any, Dict, List, Optional

async def jenkins_create_build(job_name: str, timeout: int=30, verify_ssl: bool=True, payload: Optional[Dict[str, Any]]=None, base_url: str=None) -> dict:
    """Trigger Jenkins job build. Official: https://www.jenkins.io/doc/book/using/remote-access-api/"""
    try:
        (base, err) = _jk_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        (path, perr) = _jk_job_path(job_name)
        if perr:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': perr}
        (basic, auth_err) = _jk_auth()
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err, 'provision_ids': []}
        (headers, _) = await _jk_crumb(base, basic, timeout, verify_ssl)
        endpoint = f'{base}{path}/build'
        data = None
        if isinstance(payload, dict) and payload.get('parameters'):
            endpoint = f'{base}{path}/buildWithParameters'
            data = payload.get('parameters')
        resp = await _jk_post(endpoint, basic, headers, data, timeout, verify_ssl)
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': resp['body'][:1000]}
        info_resp = await _jk_get(f'{base}{path}/api/json', basic, {'tree': 'lastBuild[number,url,result]'}, timeout, verify_ssl)
        build = info_resp['json'].get('lastBuild') if info_resp['body'] else {}
        records = _jk_single_build(build) if isinstance(build, dict) else []
        return {'records': records, 'data_count': len(records), 'status': resp['status_code'], 'message': 'ok', 'provision_ids': _jk_provision_build(build if isinstance(build, dict) else {})}
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

async def _jk_post(url, basic, headers, data, timeout, verify_ssl):
    return await nexus_call('POST', url, headers=headers, data=data)

async def _jk_crumb(base, basic, timeout, verify_ssl):
    resp = await _jk_get(f'{base}/crumbIssuer/api/json', basic, None, timeout, verify_ssl)
    if resp['status_code'] >= 400:
        return (None, None)
    data = resp['json'] if resp['body'] else {}
    if isinstance(data, dict) and data.get('crumb'):
        hdr = data.get('crumbRequestField') or 'Jenkins-Crumb'
        return ({hdr: data['crumb']}, data['crumb'])
    return ({}, None)

def _jk_single_build(data):
    if isinstance(data, dict) and data.get('number') is not None:
        return [data]
    return []

def _jk_provision_build(data):
    if isinstance(data, dict) and data.get('number') is not None:
        return [data['number']]
    return []
