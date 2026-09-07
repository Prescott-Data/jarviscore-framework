from typing import Any, Dict, List, Optional

async def mattermost_update_conversation(conversation_id: str, payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Update a channel via PUT /channels/{channel_id}. Official: https://api.mattermost.com/#tag/channels"""
    try:
        channel_id = str(conversation_id or None or None or '')
        if not channel_id:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'conversation_id is required', 'provision_ids': []}
        (root, err) = _mm_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err, 'provision_ids': []}
        (headers, aerr) = _mm_headers(json_body=True)
        if aerr:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': aerr, 'provision_ids': []}
        body = dict(payload) if isinstance(payload, dict) else {}
        body['id'] = channel_id
        resp = await nexus_call('PUT', f'{root}/channels/{channel_id}', headers=headers, json=body)
        try:
            data = resp['json'] if resp['body'] else {}
        except Exception:
            data = {}
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': _mm_error(data, resp['body']), 'provision_ids': []}
        return _mm_provision(data, resp['status_code'], fallback_id=channel_id)
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
