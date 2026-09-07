from typing import Any, Dict, List, Optional
_GA_DATA_ROOT = 'https://analyticsdata.googleapis.com/v1beta'
_GA_ADMIN_ROOT = 'https://analyticsadmin.googleapis.com/v1beta'

async def google_analytics_get_report(property_id: str, report_body: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Get a report by ID from google analytics. Official: https://developers.google.com/analytics/devguides/reporting/data/v1/rest/v1beta/properties/runReport"""
    try:
        api, err = _ga_data_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        pid, err = _ga_property_id(property_id)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        if not isinstance(report_body, dict) or not report_body:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'report_body is required'}
        headers, auth_err = _ga_auth(json_body=True)
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        url = f'{api}/{pid}:runReport'
        resp = await nexus_call('POST', url, headers=headers, json=report_body)
        status = resp['status_code']
        if status >= 400:
            return {'records': [], 'data_count': 0, 'status': status, 'message': resp['body'][:1000]}
        data = resp['json'] if resp['body'] else {}
        records = [data] if isinstance(data, dict) and data else []
        return {'records': records, 'data_count': len(records), 'status': status, 'message': 'ok'}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _ga_data_root(base_url: str):
    root = (base_url or _GA_DATA_ROOT).rstrip('/')
    if 'analyticsdata.googleapis.com' not in root:
        return (None, 'base_url must be GA4 Data API root (https://analyticsdata.googleapis.com/v1beta)')
    return (root, None)

def _ga_auth(json_body: bool=False) -> tuple:
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _ga_property_id(property_id: Optional[str]):
    pid = property_id or None or None
    if pid in (None, ''):
        return (None, 'property_id is required (or auth_info.property_id)')
    pid = str(pid)
    if not pid.startswith('properties/'):
        pid = f'properties/{pid}'
    return (pid, None)
