from typing import Any, Dict, List, Optional
_FS_API_HOST = 'https://api.fullstory.com'

async def fullstory_create_event(name: str, properties: Optional[Dict[str, Any]]=None, timestamp: Optional[str]=None, user: Optional[Dict[str, Any]]=None, session: Optional[Dict[str, Any]]=None, context: Optional[Dict[str, Any]]=None, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Create a custom server event (POST /v2/events). Requires name; optional user/session/properties. Authorization: Basic {api_key} from Settings > Integrations > API Keys (Architect for data reads). Official: https://developer.fullstory.com/"""
    try:
        if not name:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'name is required'}
        api, err = _fs_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        body: Dict[str, Any] = {'name': name}
        if properties:
            body['properties'] = properties
        if timestamp:
            body['timestamp'] = timestamp
        if user:
            body['user'] = user
        if session:
            body['session'] = session
        if context:
            body['context'] = context
        headers, auth_err = _fs_fullstory_auth(json_body=True)
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        resp = await nexus_call('POST', f'{api}/v2/events', headers=headers, json=body)
        status = resp['status_code']
        data = resp['json'] if resp['body'] else {}
        if status >= 400:
            return {'records': [], 'data_count': 0, 'status': status, 'message': resp['body'][:1000]}
        records = [data] if isinstance(data, dict) and data else []
        return {'records': records, 'data_count': len(records), 'status': status, 'message': 'ok', 'provision_ids': [name]}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _fs_api_root(base_url: str):
    root = (base_url or _FS_API_HOST).rstrip('/')
    if not root:
        return (None, 'base_url is required (https://api.fullstory.com)')
    if 'fullstory.com' not in root:
        return (None, 'base_url must be the FullStory API host (https://api.fullstory.com)')
    return (root, None)

def _fs_fullstory_auth(json_body: bool=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)
