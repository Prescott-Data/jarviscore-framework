from typing import Any, Dict, List, Optional
CRISP_API = 'https://api.crisp.chat/v1'

async def crisp_list_messages(limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """List messages from crisp. HTTP Basic site_id:api_key. Official: https://docs.crisp.chat/references/rest-api/v1/"""
    try:
        (headers, basic, site_id) = _crisp_auth()
        if not site_id or not basic:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': 'auth_info requires site_id and api_key for Basic auth'}
        (session_id, err) = _crisp_session_id()
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        api = _crisp_api_root(base_url)
        (records, status, message) = await _crisp_list_messages(api, site_id, session_id, headers, basic, limit, timeout, verify_ssl)
        return {'records': records, 'data_count': len(records), 'status': status, 'message': message}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _crisp_api_root(base_url):
    root = (base_url or CRISP_API).rstrip('/')
    if root.endswith('/v1'):
        return root
    if 'crisp.chat' in root and '/v1' not in root:
        return root + '/v1'
    return root

def _crisp_auth(json_body=False):
    headers = {'Accept': 'application/json', 'X-Crisp-Tier': 'plugin'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    site_id = None or None
    basic = None
    return (headers, basic, site_id)

async def _crisp_get(url, headers, basic, params, timeout, verify_ssl):
    return await nexus_call('GET', url, headers=headers, params=params)

def _crisp_parse(resp):
    try:
        payload = resp['json'] if resp['body'] else {}
    except Exception:
        return (None, resp['body'][:1000])
    if isinstance(payload, dict) and payload.get('error'):
        reason = payload.get('reason') or payload.get('message') or 'Crisp API error'
        return (None, str(reason))
    if isinstance(payload, dict) and 'data' in payload:
        return (payload.get('data'), 'ok')
    return (payload, 'ok')

def _crisp_records(data, single=False):
    if single:
        if isinstance(data, dict):
            return [data]
        return []
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        return [data]
    return []

def _crisp_session_id(payload=None):
    payload = payload if isinstance(payload, dict) else {}
    sid = payload.get('conversation_id') or payload.get('session_id') or None or None
    if sid:
        return (str(sid), None)
    return (None, 'Crisp messages require conversation_id (session_id) in auth_info or payload.')

async def _crisp_list_messages(api, site_id, session_id, headers, basic, limit, timeout, verify_ssl):
    records = []
    timestamp_before = None
    status = 0
    while len(records) < limit:
        params = {}
        if timestamp_before is not None:
            params['timestamp_before'] = timestamp_before
        url = f'{api}/website/{site_id}/conversation/{session_id}/messages'
        resp = await _crisp_get(url, headers, basic, params or None, timeout, verify_ssl)
        status = resp['status_code']
        if status >= 400:
            return (records, status, resp['body'][:1000])
        (data, _) = _crisp_parse(resp)
        batch = _crisp_records(data)
        if not batch:
            break
        for item in batch:
            records.append(item)
            if len(records) >= limit:
                break
        if len(batch) < 40:
            break
        last = batch[-1]
        ts = last.get('timestamp') if isinstance(last, dict) else None
        if ts is None or ts == timestamp_before:
            break
        timestamp_before = ts
    return (records[:limit], status, 'ok')
