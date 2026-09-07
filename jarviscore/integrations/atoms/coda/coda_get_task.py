from typing import Any, Dict, List, Optional
CODA_API = 'https://coda.io/apis/v1'

async def coda_get_task(task_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Get a table row (catalog task) by row id. Bearer API token in Authorization header. Official: https://coda.io/apis/v1"""
    try:
        if not task_id:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'task_id is required'}
        doc_id, table_id, err = _coda_row_context()
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        api = _coda_api_root(base_url)
        headers, auth_err = _coda_auth()
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        resp = await _coda_get(f'{api}/docs/{doc_id}/tables/{table_id}/rows/{task_id}', headers, None, timeout, verify_ssl)
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': resp['body'][:1000]}
        data = resp['json'] if resp['body'] else {}
        row = data.get('values') if isinstance(data, dict) and 'values' in data else data
        if isinstance(row, dict):
            row = dict(row)
            row.setdefault('id', task_id)
        return {'records': [row] if isinstance(row, dict) else [], 'data_count': 1 if isinstance(row, dict) else 0, 'status': resp['status_code'], 'message': 'ok'}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _coda_api_root(base_url):
    root = (base_url or CODA_API).rstrip('/')
    if _host_is(root, 'coda.io') and '/apis/v1' not in root:
        if root.endswith('/apis'):
            root = root + '/v1'
        else:
            root = root + '/apis/v1'
    return root

def _coda_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (None, 'auth_info requires api_key or access_token (Bearer)')

async def _coda_get(url, headers, params, timeout, verify_ssl):
    return await nexus_call('GET', url, headers=headers, params=params)

def _coda_row_context(payload=None):
    payload = payload if isinstance(payload, dict) else {}
    doc_id = payload.get('doc_id') or payload.get('docId') or payload.get('project_id') or None or None or None
    table_id = payload.get('table_id') or payload.get('tableId') or payload.get('table_name') or None or None or None
    if not doc_id or not table_id:
        return (None, None, 'Coda table rows require doc_id (catalog project_id) and table_id in auth_info or on payload. Endpoint: GET /docs/{docId}/tables/{tableIdOrName}/rows.')
    return (str(doc_id), str(table_id), None)

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
