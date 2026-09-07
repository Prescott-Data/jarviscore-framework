from typing import Any, Dict, List, Optional

async def phabricator_update_project(project_id: str, payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Update a project via project.edit transactions. Official: https://secure.phabricator.com/conduit/"""
    try:
        if not project_id:
            return _ph_provision({}, 400, 'project_id is required')
        (tx, err) = _ph_payload_transactions(payload, _PROJECT_TX)
        if err:
            return _ph_provision({}, 400, err)
        params = {'objectIdentifier': str(project_id).strip(), 'transactions': tx}
        (resp, result, status, msg) = await _ph_conduit('project.edit', params, base_url, timeout, verify_ssl)
        if status >= 400:
            return _ph_provision(result or {}, status, msg)
        return _ph_provision(result or {}, status, 'ok', fallback_id=project_id)
    except Exception as e:
        return _ph_provision({}, 500, str(e))

def _ph_root(base_url):
    root = (base_url or None or None or None or '').strip().rstrip('/')
    if not root:
        return (None, 'base_url is required (https://phabricator.example.com)')
    return (root, None)

def _ph_token():
    return None

def _ph_provision(result, status, msg, fallback_id=None):
    obj = result if isinstance(result, dict) else {}
    inner = obj.get('object') if isinstance(obj.get('object'), dict) else obj
    pid = None
    if isinstance(inner, dict):
        pid = inner.get('id') or inner.get('phid')
    if pid in (None, '') and fallback_id not in (None, ''):
        pid = fallback_id
    ids = [pid] if pid not in (None, '') else []
    rec = dict(inner) if isinstance(inner, dict) and inner else {'id': pid, 'phid': pid} if ids else {}
    return {'records': [rec] if rec else [], 'data_count': 1 if rec else 0, 'status': status, 'message': msg, 'provision_ids': ids}

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

def _ph_payload_transactions(payload, mapping):
    if not isinstance(payload, dict) or not payload:
        return (None, 'payload is required')
    if isinstance(payload.get('transactions'), list):
        return (payload['transactions'], None)
    tx = []
    for (key, ttype) in mapping.items():
        if key in payload and payload[key] is not None:
            tx.append({'type': ttype, 'value': payload[key]})
    if not tx:
        return (None, 'payload must include transactions or supported fields')
    return (tx, None)
_PROJECT_TX = {'name': 'name', 'description': 'description', 'icon': 'icon', 'color': 'color', 'slugs': 'slugs', 'members': 'members.set', 'members_add': 'members.add', 'members_remove': 'members.remove', 'parent': 'parent', 'milestone': 'milestone'}
