from typing import Any, Dict, List, Optional

async def amplitude_list_events(limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """List dashboard event types (GET /api/2/events/list, Basic auth). Official: https://www.docs.developers.amplitude.com/analytics/apis/dashboard-rest-api/#events-list"""
    try:
        if not base_url:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'base_url is required'}
        api_root, _, root_err = _amp_dashboard_root(base_url)
        if root_err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': root_err}
        data, status, msg = await _amp_get_json(f'{api_root}/events/list', timeout=timeout, verify_ssl=verify_ssl)
        if status >= 400:
            return {'records': [], 'data_count': 0, 'status': status, 'message': msg}
        rows = _amp_event_rows(data)
        cap = min(max(int(limit or 25), 1), 10000)
        records = [r for r in rows if isinstance(r, dict)][:cap]
        return {'records': records, 'data_count': len(records), 'status': status, 'message': 'ok'}
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
    auth, auth_err = _amp_basic_auth()
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
