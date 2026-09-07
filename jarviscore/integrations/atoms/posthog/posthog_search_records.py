from typing import Any, Dict, List, Optional

async def posthog_search_records(query: str, limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Search events via HogQL ILIKE filter. Official: https://posthog.com/docs/api/queries"""
    try:
        if not query:
            return _pg_dataset([], 400, 'query is required')
        cap = _pg_cap(limit)
        q = str(query).replace("'", "''")
        hogql = None or f"SELECT uuid, event, timestamp, distinct_id, properties FROM events WHERE event ILIKE '%{q}%' OR toString(properties) ILIKE '%{q}%' ORDER BY timestamp DESC LIMIT {cap}"
        resp, data, status, msg = await _pg_query(base_url, hogql, timeout, verify_ssl)
        if status >= 400:
            return _pg_dataset([], status, msg)
        records = _pg_query_rows(data)[:cap]
        return _pg_dataset(records, status, msg)
    except Exception as e:
        return _pg_dataset([], 500, str(e))

def _pg_app_host(base_url):
    host = (base_url or None or None or 'https://us.posthog.com').strip().rstrip('/')
    if host.endswith('/api'):
        host = host[:-4]
    return host.rstrip('/')

def _pg_project_id():
    return None or None

def _pg_private_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _pg_cap(limit):
    return min(max(int(limit or 25), 1), 10000)

def _pg_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _pg_err(resp, body=None):
    if isinstance(body, dict):
        err = body.get('detail') or body.get('error') or body.get('message')
        if err:
            return str(err)[:1000]
    return (resp['body'] if resp is not None else 'request failed')[:1000]

def _pg_query_rows(data):
    rows = []
    if not isinstance(data, dict):
        return rows
    result = data.get('results') or data.get('result')
    if isinstance(result, list):
        for item in result:
            if isinstance(item, list):
                rows.append({'values': item})
            elif isinstance(item, dict):
                rows.append(item)
    elif isinstance(result, dict):
        inner = result.get('results') or result.get('rows')
        if isinstance(inner, list):
            for item in inner:
                if isinstance(item, list):
                    rows.append({'values': item})
                elif isinstance(item, dict):
                    rows.append(item)
    columns = None
    if isinstance(data.get('columns'), list):
        columns = data.get('columns')
    elif isinstance(result, dict) and isinstance(result.get('columns'), list):
        columns = result.get('columns')
    if columns and rows and isinstance(rows[0].get('values'), list):
        fixed = []
        for row in rows:
            vals = row.get('values') or []
            obj = {}
            for i, col in enumerate(columns):
                if i < len(vals):
                    obj[str(col)] = vals[i]
            fixed.append(obj)
        return fixed
    return rows

async def _pg_request(method, url, params=None, json_body=None, timeout=30, verify_ssl=True, private=True):
    if private:
        headers, err = _pg_private_auth(json_body=json_body is not None)
    else:
        headers = {'Accept': 'application/json'}
        if json_body is not None:
            headers['Content-Type'] = 'application/json'
        err = None
    if err:
        return (None, None, 401, err)
    kwargs = {'headers': headers, 'timeout': timeout, 'verify': verify_ssl}
    if method == 'get':
        resp = await nexus_call('GET', url, params=params)
    elif method == 'post':
        resp = await nexus_call('POST', url, params=params, json=json_body)
    elif method == 'patch':
        resp = await nexus_call('PATCH', url, params=params, json=json_body)
    else:
        return (None, None, 400, f'unsupported method {method}')
    try:
        body = resp['json'] if resp['content'] else {}
    except Exception:
        body = {}
    if resp['status_code'] >= 400:
        return (resp, body, resp['status_code'], _pg_err(resp, body))
    return (resp, body, resp['status_code'], 'ok')

async def _pg_query(base_url, hogql, timeout=30, verify_ssl=True):
    project_id = _pg_project_id()
    if not project_id:
        return (None, None, 400, 'auth_info.project_id is required')
    host = _pg_app_host(base_url)
    body = {'query': {'kind': 'HogQLQuery', 'query': hogql}}
    return await _pg_request('post', host + f'/api/projects/{project_id}/query/', json_body=body, timeout=timeout, verify_ssl=verify_ssl)
