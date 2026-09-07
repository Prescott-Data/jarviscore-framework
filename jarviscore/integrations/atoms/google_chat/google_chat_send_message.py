from typing import Any, Dict, List, Optional
_CHAT_API_ROOT = 'https://chat.googleapis.com/v1'

async def google_chat_send_message(space_name: str, text: str, thread_key: Optional[str]=None, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Send a message to a Google Chat space. Official: https://developers.google.com/workspace/chat/api/reference/rest/v1/spaces.messages/create"""
    try:
        (api, err) = _chat_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err, 'provision_ids': []}
        if not space_name or not text:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'space_name and text are required', 'provision_ids': []}
        (headers, auth_err) = _chat_auth(json_body=True)
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        space = space_name if space_name.startswith('spaces/') else f'spaces/{space_name}'
        url = f'{api}/{space}/messages'
        payload: Dict[str, Any] = {'text': text}
        params = {'threadKey': thread_key} if thread_key else None
        resp = await nexus_call('POST', url, headers=headers, json=payload, params=params)
        status = resp['status_code']
        data = resp['json'] if resp['content'] else {}
        if status >= 400:
            msg = data if isinstance(data, dict) else resp['body'][:1000]
            return {'records': [], 'data_count': 0, 'status': status, 'message': str(msg), 'provision_ids': []}
        pid = data.get('name') if isinstance(data, dict) else None
        return {'records': [data] if isinstance(data, dict) else [], 'data_count': 1 if isinstance(data, dict) else 0, 'status': status, 'message': 'ok', 'provision_ids': [pid] if pid else []}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e), 'provision_ids': []}

def _chat_api_root(base_url: str):
    root = (base_url or _CHAT_API_ROOT).rstrip('/')
    if 'chat.googleapis.com' not in root:
        return (None, 'base_url must be Google Chat API root (https://chat.googleapis.com/v1)')
    return (root, None)

def _chat_auth(json_body: bool=False) -> tuple:
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)
