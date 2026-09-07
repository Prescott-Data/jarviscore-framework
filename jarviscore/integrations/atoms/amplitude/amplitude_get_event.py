from typing import Any, Dict, List, Optional

async def amplitude_get_event(event_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Find event type by name from GET /api/2/events/list (no GET-by-id endpoint). Official: https://www.docs.developers.amplitude.com/analytics/apis/dashboard-rest-api/#events-list"""
    try:
        if not base_url:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'base_url is required'}
        if not event_id:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'event_id is required'}
        (api_root, _, root_err) = _amp_dashboard_root(base_url)
        if root_err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': root_err}
        (data, status, msg) = await _amp_get_json(f'{api_root}/events/list', timeout=timeout, verify_ssl=verify_ssl)
        if status >= 400:
            return {'records': [], 'data_count': 0, 'status': status, 'message': msg}
        for row in _amp_event_rows(data):
            if _amp_match_event(row, event_id):
                return {'records': [row], 'data_count': 1, 'status': 200, 'message': 'ok'}
        return {'records': [], 'data_count': 0, 'status': 404, 'message': 'Event type not found in /events/list'}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}
_AMP_DASHBOARD_SUFFIX = '/api/2'
_AMP_DASHBOARD_HOSTS = {'https://amplitude.com', 'https://analytics.eu.amplitude.com'}
_AMP_INGEST_HOSTS = {'https://amplitude.com': 'https://api2.amplitude.com', 'https://analytics.eu.amplitude.com': 'https://api.eu.amplitude.com'}

def _amp_dashboard_root(base_url: str):
    root = base_url.rstrip('/')
    if not root.endswith(_AMP_DASHBOARD_SUFFIX):
        return (None, None, 'base_url must be https://amplitude.com/api/2 or https://analytics.eu.amplitude.com/api/2')
    host = root[:-len(_AMP_DASHBOARD_SUFFIX)]
    if host not in _AMP_DASHBOARD_HOSTS:
        return (None, None, 'base_url must be https://amplitude.com/api/2 or https://analytics.eu.amplitude.com/api/2')
    return (root, host, None)

def _amp_basic_auth():
    return (None, None)

async def _amp_get_json(url, params=None, timeout=30, verify_ssl=True):
    (auth, auth_err) = _amp_basic_auth()
    if auth_err:
        return (None, 401, auth_err)
    resp = await nexus_call('GET', url, params=params)
    status = resp['status_code']
    if status >= 400:
        return (None, status, resp['body'][:1000])
    try:
        return (resp['json'], status, 'ok')
    except Exception:
        return (None, status, 'Unexpected response format')

def _amp_event_rows(data):
    if isinstance(data, dict):
        rows = data.get('data')
        if isinstance(rows, list):
            return rows
    if isinstance(data, list):
        return data
    return []

def _amp_match_event(row, event_id: str) -> bool:
    if not isinstance(row, dict):
        return False
    target = str(event_id).strip().lower()
    for key in ('value', 'display', 'id', 'event_type'):
        val = row.get(key)
        if val is not None and str(val).strip().lower() == target:
            return True
    return False
