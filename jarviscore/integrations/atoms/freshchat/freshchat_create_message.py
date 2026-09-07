from typing import Any, Dict, List, Optional

async def freshchat_create_message(conversation_id: str, message_parts: List[Any], actor_type: Optional[str]=None, actor_id: Optional[str]=None, user_id: Optional[str]=None, message_type: str='normal', reply_parts: Optional[List[Any]]=None, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Send a message to a conversation (POST .../messages). Requires message_parts. Bearer API token from Admin > API Tokens. Base URL: https://{domain}.freshchat.com/v2. Official: https://developers.freshchat.com/api/"""
    try:
        if not conversation_id:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'conversation_id is required'}
        if not message_parts:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'message_parts is required'}
        api, err = _fc_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        body: Dict[str, Any] = {'message_parts': message_parts, 'message_type': message_type or 'normal'}
        if actor_type:
            body['actor_type'] = actor_type
        if actor_id:
            body['actor_id'] = actor_id
        if user_id:
            body['user_id'] = user_id
        if reply_parts:
            body['reply_parts'] = reply_parts
        headers, auth_err = _fc_auth(json_body=True)
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        url = f'{api}/conversations/{str(conversation_id).strip()}/messages'
        resp = await nexus_call('POST', url, headers=headers, json=body)
        status_code = resp['status_code']
        data = resp['json'] if resp['body'] else {}
        if status_code >= 400:
            return {'records': [], 'data_count': 0, 'status': status_code, 'message': resp['body'][:1000]}
        records = _fc_entity_record(data)
        return {'records': records, 'data_count': len(records), 'status': status_code, 'message': 'ok', 'provision_ids': _fc_provision_id(data)}
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

def _fc_entity_record(data):
    if isinstance(data, dict):
        if data.get('conversation_id') not in (None, ''):
            return [data]
        if data.get('id') not in (None, ''):
            return [data]
    return []

def _fc_provision_id(data):
    if not isinstance(data, dict):
        return []
    for key in ('conversation_id', 'id'):
        if data.get(key) not in (None, ''):
            return [str(data[key])]
    return []
