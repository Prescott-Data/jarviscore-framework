from typing import Any, Dict, List, Optional
MP_INGEST = 'https://api.mixpanel.com'
MP_QUERY = 'https://mixpanel.com/api/query'
MP_EXPORT = 'https://data.mixpanel.com/api/2.0'

async def mixpanel_get_event(event_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Get raw event by $insert_id via Raw Event Export API. Official: https://developer.mixpanel.com/reference/raw-event-export"""
    try:
        if not event_id:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'event_id is required ($insert_id)'}
        (root, _) = _mp_export_root(base_url)
        (pid, perr) = _mp_project_id()
        if perr:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': perr}
        (headers, aerr) = _mp_basic_headers()
        if aerr:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': aerr}
        where = f'properties["$insert_id"] == "{event_id}"'
        params = {'project_id': pid, 'where': where, 'limit': 100}
        resp = await nexus_call('GET', f'{root}/export', headers=headers, params=params)
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': _mp_error_text(resp)}
        records = _mp_jsonl(resp['body'])
        return {'records': records, 'data_count': len(records), 'status': resp['status_code'], 'message': 'ok'}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _mp_export_root(base_url):
    root = (base_url or MP_EXPORT).rstrip('/')
    if not root.endswith('/api/2.0'):
        if _host_is(root, 'mixpanel.com') and '/api/2.0' not in root:
            root = root + '/api/2.0'
    return (root, None)

def _mp_project_id(project_id=''):
    pid = project_id or None
    if pid in (None, ''):
        return (None, 'project_id is required (param or auth_info.project_id)')
    return (str(pid), None)

def _mp_basic_headers():
    import base64
    return ({'Accept': 'application/json'}, None)

def _mp_jsonl(text):
    rows = []
    import json
    for line in (text or '').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
        except Exception:
            continue
    return rows

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
    return (resp['body'] or f"HTTP {resp['status_code']}")[:1000]

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
