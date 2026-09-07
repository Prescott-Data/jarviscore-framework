from typing import Any, Dict, List, Optional

async def phabricator_list_pipelines(limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """List Harbormaster build plans (pipelines) via harbormaster.buildplan.search. Official: https://secure.phabricator.com/conduit/"""
    try:
        params = {}
        (records, status, msg) = await _ph_search('harbormaster.buildplan.search', base_url, params, limit, timeout, verify_ssl)
        return _ph_dataset(records, status, msg)
    except Exception as e:
        return _ph_dataset([], 500, str(e))

def _ph_root(base_url):
    root = (base_url or None or None or None or '').strip().rstrip('/')
    if not root:
        return (None, 'base_url is required (https://phabricator.example.com)')
    return (root, None)

def _ph_token():
    return None

def _ph_cap(limit):
    return min(max(int(limit or 25), 1), 1000)

def _ph_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _ph_rows(result):
    rows = []
    if not isinstance(result, dict):
        return rows
    for item in result.get('data') or []:
        if not isinstance(item, dict):
            continue
        row = {'id': item.get('id'), 'phid': item.get('phid')}
        fields = item.get('fields')
        if isinstance(fields, dict):
            row.update(fields)
        rows.append(row)
    return rows

def _ph_err(body, resp):
    if isinstance(body, dict):
        info = body.get('error_info') or body.get('error_code') or body.get('errorMessage')
        if info:
            return str(info)[:1000]
    return (resp['body'] if resp is not None else 'request failed')[:1000]

async def _ph_conduit(method, params, base_url, timeout=30, verify_ssl=True):
    import json
    (root, err) = _ph_root(base_url)
    if err:
        return (None, None, 400, err)
    tok = _ph_token()
    if not tok:
        return (None, None, 401, 'auth_info.api_key is required')
    form = {'api.token': str(tok).strip()}
    for (key, val) in (params or {}).items():
        if val is None:
            continue
        if isinstance(val, (dict, list)):
            form[key] = json.dumps(val)
        else:
            form[key] = str(val)
    url = root + '/api/' + method
    resp = await nexus_call('POST', url, data=form)
    try:
        body = resp['json'] if resp['content'] else {}
    except Exception:
        body = {}
    if resp['status_code'] >= 400:
        return (resp, body, resp['status_code'], _ph_err(body, resp))
    if isinstance(body, dict) and body.get('error_code'):
        return (resp, body, 400, _ph_err(body, resp))
    result = body.get('result') if isinstance(body, dict) else None
    return (resp, result, 200, 'ok')

async def _ph_search(method, base_url, base_params, limit, timeout, verify_ssl):
    cap = _ph_cap(limit)
    records = []
    after = None
    status = 200
    msg = 'ok'
    while len(records) < cap:
        params = dict(base_params or {})
        params['limit'] = min(100, cap - len(records))
        if after:
            params['after'] = after
        (resp, result, status, msg) = await _ph_conduit(method, params, base_url, timeout, verify_ssl)
        if status >= 400:
            return (records[:cap], status, msg)
        batch = _ph_rows(result)
        records.extend(batch)
        cursor = result.get('cursor') if isinstance(result, dict) else None
        after = cursor.get('after') if isinstance(cursor, dict) else None
        if not after or not batch:
            break
    return (records[:cap], status, msg)
