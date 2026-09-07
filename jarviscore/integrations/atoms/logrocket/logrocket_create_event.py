from typing import Any, Dict, List, Optional
LOGROCKET_API = 'https://api.logrocket.com/v1'

async def logrocket_create_event(org_id: str, app_id: str, user_id: str, payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Create or update user traits via User Identification API. Official: https://docs.logrocket.com/docs/user-identification-api"""
    try:
        uid = user_id or (payload or {}).get('user_id') or (payload or {}).get('userID')
        if not uid:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'user_id is required', 'provision_ids': []}
        (app_base, err) = _lr_app_base(base_url, org_id, app_id)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err, 'provision_ids': []}
        (headers, aerr) = _lr_headers(json_body=True)
        if aerr:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': aerr, 'provision_ids': []}
        body = payload if isinstance(payload, dict) else {}
        resp = await nexus_call('PUT', f'{app_base}/users/{uid}', headers=headers, json=body)
        try:
            data = resp['json'] if resp['body'] else {}
        except Exception:
            data = {}
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': resp['body'][:1000], 'provision_ids': []}
        result = _lr_provision(data, resp['status_code'], fallback_id=uid)
        if not result['provision_ids']:
            result['provision_ids'] = [uid]
        return result
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e), 'provision_ids': []}

def _lr_org_app(org_id, app_id):
    org = org_id or None
    app = app_id or None
    if not org or not app:
        return (None, None, 'org_id and app_id are required')
    return (str(org), str(app), None)

def _lr_app_base(base_url, org_id, app_id):
    (org, app, err) = _lr_org_app(org_id, app_id)
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

def _lr_provision(data, status, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    obj_id = obj.get('id') or obj.get('requestID') or obj.get('userID') or fallback_id
    ids = [obj_id] if obj_id not in (None, '') else []
    records = [obj] if obj else [{'id': obj_id}] if obj_id else []
    return {'records': records, 'data_count': len(records), 'status': status, 'message': 'ok' if status < 400 else str(obj)[:1000], 'provision_ids': ids}
