from typing import Any, Dict, List, Optional

async def freshchat_list_conversations(user_id: str, limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """List conversations for a user (GET .../users/{userId}/conversations). Response.conversations[]. Bearer API token from Admin > API Tokens. Base URL: https://{domain}.freshchat.com/v2. Official: https://developers.freshchat.com/api/"""
    try:
        if not user_id:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'user_id is required'}
        (api, err) = _fc_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        (headers, auth_err) = _fc_auth()
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        url = f'{api}/users/{str(user_id).strip()}/conversations'
        resp = await nexus_call('GET', url, headers=headers)
        status = resp['status_code']
        if status >= 400:
            return {'records': [], 'data_count': 0, 'status': status, 'message': resp['body'][:1000]}
        data = resp['json'] if resp['body'] else {}
        records = _fc_list_batch(data, 'conversations')
        cap = min(max(int(limit or 25), 1), 1000)
        records = records[:cap]
        return {'records': records, 'data_count': len(records), 'status': status, 'message': 'ok'}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _fc_api_root(base_url: str):
    root = (base_url or '').rstrip('/')
    if not root:
        return (None, 'base_url is required (https://{domain}.freshchat.com/v2)')
    if 'freshchat.com' not in root:
        return (None, 'base_url must be the Freshchat API v2 root (https://{domain}.freshchat.com/v2)')
    if not root.endswith('/v2'):
        root = root + '/v2'
    return (root, None)

def _fc_auth(json_body: bool=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _fc_list_batch(data, collection_key):
    if not isinstance(data, dict):
        return []
    batch = data.get(collection_key)
    if not isinstance(batch, list):
        return []
    return [item for item in batch if isinstance(item, dict)]
