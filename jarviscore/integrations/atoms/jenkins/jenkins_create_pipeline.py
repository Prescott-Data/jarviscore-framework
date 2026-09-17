from typing import Any, Dict, List, Optional

async def jenkins_create_pipeline(payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Create Jenkins pipeline job. Official: https://www.jenkins.io/doc/book/using/remote-access-api/"""
    try:
        if not payload:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'payload is required'}
        name = payload.get('name') or payload.get('job_name')
        if not name:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'payload.name is required'}
        (base, err) = _jk_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        (basic, auth_err) = _jk_auth()
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err, 'provision_ids': []}
        (headers, _) = await _jk_crumb(base, basic, timeout, verify_ssl)
        headers['Content-Type'] = 'application/xml'
        config = payload.get('config_xml') or payload.get('config')
        if not config:
            config = '<?xml version=\'1.0\' encoding=\'UTF-8\'?><flow-definition plugin="workflow-job"><definition class="org.jenkinsci.plugins.workflow.cps.CpsFlowDefinition"><script>pipeline { agent any; stages { stage(\'Build\'){ steps { echo \'hi\' } } } }</script></definition></flow-definition>'
        resp = await _jk_post(f'{base}/createItem?name={name}', basic, headers, config, timeout, verify_ssl)
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': resp['body'][:1000]}
        return {'records': [{'name': name}], 'data_count': 1, 'status': resp['status_code'], 'message': 'ok', 'provision_ids': [name]}
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
