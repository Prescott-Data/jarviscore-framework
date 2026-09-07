from typing import Any, Dict, List, Optional, Tuple, Union
LP_CLASSIC_API = 'https://app.liquidplanner.com/api/v1'

async def liquidplanner_search_records(workspace_id: str, query: str, limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Search treeitems by name contains filter. Official: https://developer.liquidplanner.com/docs/filtering-requests"""
    try:
        if not query:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'query is required'}
        (base, err) = _lp_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        (ws, werr) = _lp_workspace(workspace_id)
        if werr:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': werr}
        (headers, aerr) = _lp_headers()
        if aerr:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': aerr}
        filt = 'name contains ' + _lp_filter_quote(query)
        params = [('filter[]', filt), ('flat', 'true')]
        resp = await nexus_call('GET', f'{base}/workspaces/{ws}/treeitems', headers=headers, params=params)
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': resp['body'][:1000]}
        try:
            data = resp['json'] if resp['body'] else []
        except Exception:
            data = []
        records = _lp_cap(_lp_records(data), limit)
        return {'records': records, 'data_count': len(records), 'status': resp['status_code'], 'message': 'ok'}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _lp_root(base_url):
    root = (base_url or LP_CLASSIC_API).rstrip('/')
    if 'liquidplanner.com' not in root:
        return (None, 'base_url must be https://app.liquidplanner.com/api/v1')
    return (root, None)

def _lp_workspace(workspace_id):
    ws = workspace_id or None
    if ws in (None, ''):
        return (None, 'workspace_id is required')
    return (str(ws), None)

def _lp_auth_header():
    prefix = 'Bearer '
    return (None, None)

def _lp_headers(json_body=False):
    (auth, err) = _lp_auth_header()
    if err:
        return (None, err)
    headers = {'Accept': 'application/json', 'Authorization': auth}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _lp_records(data):
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        if data.get('type') == 'Error':
            return []
        if data.get('id') is not None:
            return [data]
    return []

def _lp_filter_quote(value):
    text = str(value or '')
    text = text.replace('\\', '\\\\').replace('"', '\\"')
    return '"' + text + '"'

def _lp_cap(records, limit):
    cap = min(max(int(limit or 25), 1), 500)
    return records[:cap]
