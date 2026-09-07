from typing import Any, Dict, List, Optional

async def okta_update_group(domain: str, group_id: str, payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Replace group profile. Official: https://developer.okta.com/docs/reference/api/overview/"""
    try:
        if not group_id:
            return _ok_provision({}, 400, 'group_id is required')
        if not isinstance(payload, dict) or not payload:
            return _ok_provision({}, 400, 'payload is required')
        (root, err) = _ok_root(base_url, domain)
        if err:
            return _ok_provision({}, 400, err)
        (headers, aerr) = _ok_auth(json_body=True)
        if aerr:
            return _ok_provision({}, 400, aerr)
        resp = await nexus_call('PUT', f'{root}/groups/{group_id}', headers=headers, json=payload)
        status = resp['status_code']
        if status >= 400:
            return _ok_provision({}, status, _ok_error(resp))
        try:
            data = resp['json']
        except Exception:
            return _ok_provision({}, status, resp['body'][:1000])
        return _ok_provision(data if isinstance(data, dict) else {}, status, 'ok', fallback_id=group_id)
    except Exception as e:
        return _ok_provision({}, 500, str(e))

def _ok_root(base_url, domain):
    root = (base_url or None or '').strip().rstrip('/')
    dom = (domain or None or None or '').strip()
    if dom:
        dom = dom.replace('https://', '').replace('http://', '').rstrip('/')
    if not root and dom:
        root = f'https://{dom}/api/v1'
    if root and '/api/v1' not in root:
        if 'okta' in root.lower():
            root = root + '/api/v1'
    if not root:
        return (None, 'base_url or domain is required (https://{yourOktaDomain}/api/v1)')
    return (root, None)

def _ok_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _ok_error(resp):
    try:
        data = resp['json']
        if isinstance(data, dict):
            msg = data.get('errorSummary') or data.get('errorCode') or data.get('message')
            if msg:
                return str(msg)[:1000]
    except Exception:
        pass
    return (resp['body'] or f"HTTP {resp['status_code']}")[:1000]

def _ok_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get('id') or fallback_id
    ids = [pid] if pid not in (None, '') else []
    rec = obj if obj else {'id': pid} if ids else {}
    return {'records': [rec] if rec else [], 'data_count': 1 if rec else 0, 'status': status, 'message': msg, 'provision_ids': ids}
