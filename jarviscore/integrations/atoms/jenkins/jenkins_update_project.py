from typing import Any, Dict, List, Optional

async def jenkins_update_project(job_name: str, payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Update Jenkins job config XML. Official: https://www.jenkins.io/doc/book/using/remote-access-api/"""
    try:
        (path, perr) = _jk_job_path(job_name)
        if perr:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': perr}
        config = (payload or {}).get('config_xml') or (payload or {}).get('config')
        if not config:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'payload.config_xml is required'}
        (base, err) = _jk_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        (basic, auth_err) = _jk_auth()
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        (headers, _) = await _jk_crumb(base, basic, timeout, verify_ssl)
        headers['Content-Type'] = 'application/xml'
        resp = await _jk_post(f'{base}{path}/config.xml', basic, headers, config, timeout, verify_ssl)
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': resp['body'][:1000]}
        return {'records': [{'name': job_name}], 'data_count': 1, 'status': resp['status_code'], 'message': 'ok'}
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
