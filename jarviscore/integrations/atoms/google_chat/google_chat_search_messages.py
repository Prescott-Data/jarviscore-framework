from typing import Any, Dict, List, Optional
_CHAT_API_ROOT = 'https://chat.googleapis.com/v1'

async def google_chat_search_messages(space_name: str, filter_expr: str, max_results: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """List messages with filter (createTime, thread.name). Official: https://developers.google.com/workspace/chat/api/reference/rest/v1/spaces.messages/list"""
    try:
        (api, err) = _chat_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        if not space_name or not filter_expr:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'space_name and filter_expr are required (createTime/thread.name filter syntax)'}
        (headers, auth_err) = _chat_auth()
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        space = space_name if space_name.startswith('spaces/') else f'spaces/{space_name}'
        url = f'{api}/{space}/messages'
        (records, status, msg) = await _chat_page(url, headers, {'filter': filter_expr}, 'messages', max_results, timeout, verify_ssl)
        if status >= 400 or msg != 'ok':
            return {'records': records, 'data_count': len(records), 'status': status, 'message': msg}
        return {'records': records, 'data_count': len(records), 'status': status, 'message': 'ok'}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

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

async def _chat_page(url: str, headers: Dict[str, str], params: Dict[str, Any], item_key: str, limit: int, timeout: int, verify_ssl: bool) -> tuple:
    records: List[Dict[str, Any]] = []
    cap = min(max(int(limit or 25), 1), 1000)
    page_token = None
    status = 0
    while len(records) < cap:
        q = dict(params)
        q['pageSize'] = min(100, cap - len(records))
        if page_token:
            q['pageToken'] = page_token
        resp = await nexus_call('GET', url, headers=headers, params=q)
        status = resp['status_code']
        if status >= 400:
            return (records, status, resp['body'][:1000])
        data = resp['json'] if resp['body'] else {}
        items = data.get(item_key) if isinstance(data, dict) else None
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    records.append(item)
                    if len(records) >= cap:
                        break
        page_token = data.get('nextPageToken') if isinstance(data, dict) else None
        if not page_token or len(records) >= cap:
            break
    return (records, status, 'ok')
