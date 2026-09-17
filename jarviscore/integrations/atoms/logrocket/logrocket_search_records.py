from typing import Any, Dict, List, Optional
LOGROCKET_API = 'https://api.logrocket.com/v1'

async def logrocket_search_records(org_id: str, app_id: str, query: str='', limit: int=25, cursor: str='', timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """List exported session files via Data Export API. Official: https://docs.logrocket.com/docs/data-export"""
    try:
        (app_base, err) = _lr_app_base(base_url, org_id, app_id)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        (headers, aerr) = _lr_headers()
        if aerr:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': aerr}
        params = {'limit': min(max(int(limit or 25), 1), 100)}
        if cursor:
            params['cursor'] = cursor
        elif query and str(query).isdigit():
            params['date'] = str(query)
        resp = await nexus_call('GET', f'{app_base}/data-export/', headers=headers, params=params)
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': resp['body'][:1000]}
        try:
            data = resp['json'] if resp['body'] else {}
        except Exception:
            data = {}
        records = _lr_cap(_lr_records(data.get('sessions') if isinstance(data, dict) else None), limit)
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

def _lr_records(items):
    if isinstance(items, list):
        return [row for row in items if isinstance(row, dict)]
    if isinstance(items, dict) and items.get('id') is not None:
        return [items]
    return []

def _lr_cap(records, limit):
    cap = min(max(int(limit or 25), 1), 100)
    return records[:cap]
