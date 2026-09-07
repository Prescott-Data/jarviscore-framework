from typing import Any, Dict, List, Optional

async def mattermost_create_conversation(payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Create a channel via POST /channels. Official: https://api.mattermost.com/#tag/channels"""
    try:
        root, err = _mm_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err, 'provision_ids': []}
        headers, aerr = _mm_headers(json_body=True)
        if aerr:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': aerr, 'provision_ids': []}
        body, berr = _mm_channel_body(payload)
        if berr:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': berr, 'provision_ids': []}
        resp = await nexus_call('POST', f'{root}/channels', headers=headers, json=body)
        try:
            data = resp['json'] if resp['body'] else {}
        except Exception:
            data = {}
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': _mm_error(data, resp['body']), 'provision_ids': []}
        return _mm_provision(data, resp['status_code'])
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e), 'provision_ids': []}

def _mm_api_root(base_url):
    root = (base_url or '').rstrip('/')
    if not root:
        return (None, 'base_url is required')
    if not root.endswith('/api/v4'):
        root = root + '/api/v4'
    return (root, None)

def _mm_headers(json_body=False):
    prefix = 'Bearer '
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _mm_error(data, fallback=''):
    if isinstance(data, dict):
        msg = data.get('message') or data.get('detailed_error')
        if msg:
            return str(msg)[:1000]
    return (fallback or '')[:1000]

def _mm_provision(data, status, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    obj_id = obj.get('id') or fallback_id
    ids = [obj_id] if obj_id not in (None, '') else []
    records = [obj] if obj else [{'id': obj_id}] if obj_id else []
    return {'records': records, 'data_count': len(records), 'status': status, 'message': 'ok' if status < 400 else _mm_error(data, str(obj)), 'provision_ids': ids}

def _mm_channel_body(payload):
    body = dict(payload) if isinstance(payload, dict) else {}
    team_id = body.get('team_id') or None
    name = body.get('name') or body.get('channel_name')
    display_name = body.get('display_name') or body.get('displayName') or name
    channel_type = body.get('type') or body.get('channel_type') or 'O'
    if not team_id or not name or (not display_name):
        return (None, 'payload.team_id, payload.name, and payload.display_name are required')
    out = {'team_id': str(team_id), 'name': str(name), 'display_name': str(display_name), 'type': str(channel_type)}
    for key in ('purpose', 'header'):
        if body.get(key) not in (None, ''):
            out[key] = body.get(key)
    return (out, None)
