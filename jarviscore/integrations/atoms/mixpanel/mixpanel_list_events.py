from typing import Any, Dict, List, Optional
MP_INGEST = 'https://api.mixpanel.com'
MP_QUERY = 'https://mixpanel.com/api/query'
MP_EXPORT = 'https://data.mixpanel.com/api/2.0'

async def mixpanel_list_events(limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """List top event names via Query API /events/names. Official: https://developer.mixpanel.com/reference/query-months-top-event-names"""
    try:
        root, _ = _mp_query_root(base_url)
        pid, perr = _mp_project_id()
        if perr:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': perr}
        headers, aerr = _mp_basic_headers()
        if aerr:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': aerr}
        params = {'project_id': pid, 'type': 'general', 'limit': _mp_cap(limit)}
        resp = await nexus_call('GET', f'{root}/events/names', headers=headers, params=params)
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': _mp_error_text(resp)}
        try:
            names = resp['json']
        except Exception:
            names = []
        records = [{'name': n} for n in names if isinstance(n, str)][:_mp_cap(limit)]
        return {'records': records, 'data_count': len(records), 'status': resp['status_code'], 'message': 'ok'}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _mp_query_root(base_url):
    root = (base_url or MP_QUERY).rstrip('/')
    if not root.endswith('/api/query'):
        if _host_is(root, 'mixpanel.com') and '/api/query' not in root:
            root = root + '/api/query'
    return (root, None)

def _mp_project_id(project_id=''):
    pid = project_id or None
    if pid in (None, ''):
        return (None, 'project_id is required (param or auth_info.project_id)')
    return (str(pid), None)

def _mp_basic_headers():
    import base64
    return ({'Accept': 'application/json'}, None)

def _mp_cap(limit):
    return min(max(int(limit or 25), 1), 1000)

def _mp_error_text(resp):
    try:
        data = resp['json']
        if isinstance(data, dict):
            if data.get('error'):
                return str(data.get('error'))[:1000]
            if data.get('status') == 'error':
                return str(data.get('error') or data)[:1000]
    except Exception:
        pass
    return (resp['body'] or f'HTTP {resp['status_code']}')[:1000]

def _host_is(url, *domains):
    """True only if url's hostname equals or is a subdomain of one of domains."""
    from urllib.parse import urlparse
    u = str(url or '').strip()
    if '://' not in u:
        u = 'https://' + u
    try:
        host = (urlparse(u).hostname or '').lower()
    except Exception:
        return False
    return any((host == d or host.endswith('.' + d) for d in domains))
