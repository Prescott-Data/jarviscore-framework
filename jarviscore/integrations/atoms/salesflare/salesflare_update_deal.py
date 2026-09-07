from typing import Any, Dict, List, Optional

async def salesflare_update_deal(deal_id: str, payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Update opportunity. Official: https://api.salesflare.com/docs"""
    try:
        if not deal_id:
            return _sf_provision({}, 400, 'deal_id is required')
        if not isinstance(payload, dict) or not payload:
            return _sf_provision({}, 400, 'payload is required', deal_id)
        resp, body, status, msg = await _sf_request('PUT', f'/opportunities/{deal_id}', base_url, None, payload, timeout, verify_ssl)
        if status >= 400:
            return _sf_provision(body if isinstance(body, dict) else {}, status, msg, deal_id)
        return _sf_provision(body if isinstance(body, dict) else {}, status, 'ok', deal_id)
    except Exception as e:
        return _sf_provision({}, 500, str(e), deal_id)

def _sf_root(base_url):
    root = (base_url or None or None or 'https://api.salesflare.com').strip().rstrip('/')
    return (root, None)

def _sf_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _sf_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get('id') or obj.get('ID') or fallback_id
    ids = [pid] if pid not in (None, '') else []
    rec = obj if obj else {'id': pid} if ids else {}
    return {'records': [rec] if rec else [], 'data_count': 1 if rec else 0, 'status': status, 'message': msg, 'provision_ids': ids}

def _sf_err(resp, body=None):
    if isinstance(body, dict):
        for key in ('message', 'error', 'errorMessage', 'detail'):
            if body.get(key):
                return str(body.get(key))[:1000]
    return (resp['body'] if resp is not None else 'request failed')[:1000]

async def _sf_request(method, path, base_url, params, json_body, timeout, verify_ssl):
    headers, err = _sf_auth(json_body=json_body is not None)
    if err:
        return (None, None, 401, err)
    root, _ = _sf_root(base_url)
    resp = await nexus_call(method, root + path, headers=headers, params=params, json=json_body)
    try:
        body = resp['json'] if resp['content'] else {}
    except Exception:
        body = {}
    if resp['status_code'] >= 400:
        return (resp, body, resp['status_code'], _sf_err(resp, body))
    return (resp, body, resp['status_code'], 'ok')
