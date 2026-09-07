from typing import Any, Dict, List, Optional

async def mattermost_list_conversations(team_id: str='', user_id: str='', limit: int=25, page: int=0, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """List channels for a user via GET /users/me/channels or GET /users/me/teams/{team_id}/channels. Official: https://api.mattermost.com/#tag/channels"""
    try:
        root, err = _mm_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        headers, aerr = _mm_headers()
        if aerr:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': aerr}
        team = _mm_team_id(team_id)
        user = _mm_user_id(user_id)
        per_page = min(max(int(limit or 25), 1), 200)
        records: List[Dict[str, Any]] = []
        status = 0
        if team:
            url = f'{root}/users/{user}/teams/{team}/channels'
        else:
            url = f'{root}/users/{user}/channels'
        resp = await nexus_call('GET', url, headers=headers)
        status = resp['status_code']
        try:
            data = resp['json'] if resp['body'] else []
        except Exception:
            data = []
        if status >= 400:
            return {'records': [], 'data_count': 0, 'status': status, 'message': _mm_error(data, resp['body'])}
        records = _mm_records(data)
        if team and page:
            start = max(int(page or 0), 0) * per_page
            records = records[start:start + per_page]
        records = _mm_cap(records, limit)
        return {'records': records, 'data_count': len(records), 'status': status, 'message': 'ok'}
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

def _mm_team_id(team_id):
    val = team_id or None
    return str(val) if val not in (None, '') else ''

def _mm_user_id(user_id):
    val = user_id or None or 'me'
    return str(val)

def _mm_records(data):
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    return []

def _mm_cap(records, limit):
    cap = min(max(int(limit or 25), 1), 200)
    return records[:cap]

def _mm_error(data, fallback=''):
    if isinstance(data, dict):
        msg = data.get('message') or data.get('detailed_error')
        if msg:
            return str(msg)[:1000]
    return (fallback or '')[:1000]
