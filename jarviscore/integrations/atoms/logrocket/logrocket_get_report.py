from typing import Any, Dict, List, Optional
LOGROCKET_API = 'https://api.logrocket.com/v1'

async def logrocket_get_report(org_id: str, app_id: str, report_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Poll Highlights results by request id. Official: https://docs.logrocket.com/docs/session-highlights-api"""
    try:
        if not report_id:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'report_id is required'}
        app_base, err = _lr_app_base(base_url, org_id, app_id)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        headers, aerr = _lr_headers()
        if aerr:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': aerr}
        resp = await nexus_call('GET', f'{app_base}/highlights', headers=headers, params={'id': report_id})
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': resp['body'][:1000]}
        try:
            data = resp['json'] if resp['body'] else {}
        except Exception:
            data = {}
        records = [data] if isinstance(data, dict) and data else []
        return {'records': records, 'data_count': len(records), 'status': resp['status_code'], 'message': 'ok'}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _lr_org_app(org_id, app_id):
    org = org_id or None
    app = app_id or None
    if not org or not app:
        return (None, None, 'org_id and app_id are required')
    return (str(org), str(app), None)

def _lr_app_base(base_url, org_id, app_id):
    org, app, err = _lr_org_app(org_id, app_id)
    if err:
        return (None, err)
    root = (base_url or LOGROCKET_API).rstrip('/')
    if '/orgs/' in root and '/apps/' in root:
        return (root, None)
    return (f'{root}/orgs/{org}/apps/{app}', None)

def _lr_headers(json_body=False):
    prefix = 'token '
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)
