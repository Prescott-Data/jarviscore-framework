from typing import Any, Dict, List, Optional

async def proofhub_search_records(query: str, limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Search projects and tasks by title client-side. Official: https://github.com/ProofHub/api_v3/blob/master/README.md"""
    try:
        if not query:
            return _ph_dataset([], 400, 'query is required')
        root, err = _ph_root(base_url)
        if err:
            return _ph_dataset([], 400, err)
        cap = _ph_cap(limit)
        out = []
        resp, body, status, msg = await _ph_request('get', root + '/projects', timeout=timeout, verify_ssl=verify_ssl)
        if status >= 400:
            return _ph_dataset([], status, msg)
        for row in _ph_rows(body):
            if _ph_match(row, query):
                row = dict(row)
                row['record_type'] = 'project'
                out.append(row)
            if len(out) >= cap:
                break
        if len(out) < cap:
            tasks, tstatus, tmsg = await _ph_collect_tasks(root, cap * 3, timeout, verify_ssl)
            if tstatus >= 400 and (not out):
                return _ph_dataset([], tstatus, tmsg)
            for row in tasks:
                if _ph_match(row, query):
                    item = dict(row)
                    item['record_type'] = 'task'
                    out.append(item)
                if len(out) >= cap:
                    break
        return _ph_dataset(out[:cap], 200, 'ok')
    except Exception as e:
        return _ph_dataset([], 500, str(e))

def _ph_root(base_url):
    root = (base_url or None or None or None or '').strip().rstrip('/')
    if not root:
        return (None, 'base_url is required (https://company.proofhub.com/api/v3)')
    if '/api/v3' not in root:
        root = root + '/api/v3'
    return (root, None)

def _ph_auth(json_body=False):
    ua = None or None or 'jarviscoreIntegration (integration@jarviscore.io)'
    headers = {'User-Agent': str(ua).strip(), 'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _ph_cap(limit):
    return min(max(int(limit or 25), 1), 100)

def _ph_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _ph_err(resp, body=None):
    if isinstance(body, dict):
        err = body.get('message') or body.get('error')
        if err:
            return str(err)[:1000]
    try:
        if resp is not None and resp['content']:
            data = resp['json']
            if isinstance(data, dict) and data.get('message'):
                return str(data.get('message'))[:1000]
    except Exception:
        pass
    return (resp['body'] if resp is not None else 'request failed')[:1000]

def _ph_rows(body):
    if isinstance(body, list):
        return [x for x in body if isinstance(x, dict)]
    if isinstance(body, dict):
        for key in ('todos', 'results', 'data', 'items'):
            val = body.get(key)
            if isinstance(val, list):
                return [x for x in val if isinstance(x, dict)]
        return [body]
    return []

async def _ph_request(method, url, params=None, json_body=None, timeout=30, verify_ssl=True):
    headers, err = _ph_auth(json_body=json_body is not None)
    if err:
        return (None, None, 401, err)
    kwargs = {'headers': headers, 'timeout': timeout, 'verify': verify_ssl}
    if method == 'get':
        resp = await nexus_call('GET', url, params=params)
    elif method == 'post':
        resp = await nexus_call('POST', url, params=params, json=json_body)
    elif method == 'put':
        resp = await nexus_call('PUT', url, params=params, json=json_body)
    else:
        return (None, None, 400, f'unsupported method {method}')
    try:
        body = resp['json'] if resp['content'] else {}
    except Exception:
        body = {}
    if resp['status_code'] >= 400:
        return (resp, body, resp['status_code'], _ph_err(resp, body))
    return (resp, body, resp['status_code'], 'ok')

def _ph_match(record, query):
    q = str(query).lower()
    for key in ('id', 'title', 'description', 'ticket', 'name'):
        val = record.get(key)
        if val is not None and q in str(val).lower():
            return True
    return False

async def _ph_fetch_list_tasks(root, project_id, todolist_id, cap, timeout, verify_ssl):
    url = root + f'/projects/{project_id}/todolists/{todolist_id}/tasks'
    resp, body, status, msg = await _ph_request('get', url, timeout=timeout, verify_ssl=verify_ssl)
    if status >= 400:
        return ([], status, msg)
    rows = _ph_rows(body)
    for row in rows:
        row.setdefault('project_id', project_id)
        row.setdefault('todolist_id', todolist_id)
    return (rows[:cap], status, msg)

async def _ph_collect_tasks(root, cap, timeout, verify_ssl, project_id=None):
    records = []
    status = 200
    msg = 'ok'
    if project_id:
        resp, body, status, msg = await _ph_request('get', root + f'/projects/{project_id}/todolists', timeout=timeout, verify_ssl=verify_ssl)
        if status >= 400:
            return ([], status, msg)
        lists = _ph_rows(body)
    else:
        start = 0
        lists = []
        while len(lists) < cap:
            page = min(100, cap)
            resp, body, status, msg = await _ph_request('get', root + '/alltodo', params={'start': start, 'limit': page}, timeout=timeout, verify_ssl=verify_ssl)
            if status >= 400:
                return ([], status, msg)
            batch = _ph_rows(body)
            if not batch:
                break
            lists.extend(batch)
            if len(batch) < page:
                break
            start += page
    for lst in lists:
        if len(records) >= cap:
            break
        lid = lst.get('id')
        pid = project_id or (lst.get('project') or {}).get('id')
        if not pid or not lid:
            continue
        batch, status, msg = await _ph_fetch_list_tasks(root, pid, lid, cap - len(records), timeout, verify_ssl)
        if status >= 400 and (not records):
            return ([], status, msg)
        records.extend(batch)
    return (records[:cap], status, msg)
