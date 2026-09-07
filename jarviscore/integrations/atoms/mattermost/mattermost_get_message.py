from typing import Any, Dict, List, Optional

async def mattermost_get_message(message_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Get a post by id via GET /posts/{post_id}. Official: https://api.mattermost.com/#tag/posts"""
    try:
        if not message_id:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'message_id is required (post id)'}
        root, err = _mm_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        headers, aerr = _mm_headers()
        if aerr:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': aerr}
        resp = await nexus_call('GET', f'{root}/posts/{message_id}', headers=headers)
        try:
            data = resp['json'] if resp['body'] else {}
        except Exception:
            data = {}
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': _mm_error(data, resp['body'])}
        records = [data] if isinstance(data, dict) and data.get('id') else [data] if isinstance(data, dict) else []
        return {'records': records, 'data_count': len(records), 'status': resp['status_code'], 'message': 'ok'}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _mm_api_root(base_url):
    root = (base_url or '').rstrip('/')
    if not root:
        return (None, 'base_url is required')
    if not root.endswith('/api/v4'):
        root = root + '/api/v4'
    return (root, None)

def _mm_headers():
    prefix = 'Bearer '
    return ({'Accept': 'application/json'}, None)

def _mm_error(data, fallback=''):
    if isinstance(data, dict):
        msg = data.get('message') or data.get('detailed_error')
        if msg:
            return str(msg)[:1000]
    return (fallback or '')[:1000]
