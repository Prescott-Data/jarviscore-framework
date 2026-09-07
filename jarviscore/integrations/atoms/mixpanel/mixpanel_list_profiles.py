from typing import Any, Dict, List, Optional
MP_INGEST = 'https://api.mixpanel.com'
MP_QUERY = 'https://mixpanel.com/api/query'
MP_EXPORT = 'https://data.mixpanel.com/api/2.0'

async def mixpanel_list_profiles(limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """List user profiles via Query API engage with pagination. Official: https://developer.mixpanel.com/reference/engage-query"""
    try:
        cap = _mp_cap(limit)
        records: List[Dict[str, Any]] = []
        session_id = None
        page = 0
        status = 0
        while len(records) < cap and page < 50:
            form: Dict[str, Any] = {}
            if page == 0:
                form['include_all_users'] = 'true'
            else:
                form['session_id'] = session_id
                form['page'] = str(page)
            (data, status, msg) = await _mp_engage_query(base_url, '', form, timeout, verify_ssl)
            if status >= 400 or not isinstance(data, dict):
                if records:
                    break
                return {'records': [], 'data_count': 0, 'status': status, 'message': msg}
            batch = [row for row in data.get('results') or [] if isinstance(row, dict)]
            records.extend(batch)
            session_id = data.get('session_id') or session_id
            page_size = int(data.get('page_size') or 0)
            if not batch or (page_size and len(batch) < page_size):
                break
            page += 1
        records = records[:cap]
        return {'records': records, 'data_count': len(records), 'status': status, 'message': 'ok'}
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
    return (resp['body'] or f"HTTP {resp['status_code']}")[:1000]

async def _mp_engage_query(base_url, project_id, form_data, timeout, verify_ssl):
    (root, _) = _mp_query_root(base_url)
    (pid, perr) = _mp_project_id(project_id)
    if perr:
        return (None, 400, perr)
    (headers, aerr) = _mp_basic_headers()
    if aerr:
        return (None, 400, aerr)
    headers['Content-Type'] = 'application/x-www-form-urlencoded'
    resp = await nexus_call('POST', f'{root}/engage', params={'project_id': pid}, headers=headers, data=form_data or {})
    if resp['status_code'] >= 400:
        return (None, resp['status_code'], _mp_error_text(resp))
    try:
        return (resp['json'], resp['status_code'], 'ok')
    except Exception:
        return (None, resp['status_code'], resp['body'][:1000])

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
