async def zoom_list_meetings(user_id: str='me', meeting_type: str='scheduled', page_size: int=30) -> list:
    """List meetings via the zoom API."""
    _base = 'https://api.zoom.us/v2'
    _h = {'Content-Type': 'application/json'}

    async def _get(p, params=None, headers=None):
        _r = await nexus_call('GET', f'{_base}{p}', headers={**_h, **(headers or {})}, params=params or {})
        if not _r['ok']:
            return {'success': False, 'error': _r['body']}
        return _r['json']

    async def _post(p, data=None, headers=None):
        _r = await nexus_call('POST', f'{_base}{p}', headers={**_h, **(headers or {})}, json=data)
        if not _r['ok']:
            return {'success': False, 'error': _r['body']}
        return _r['json']

    async def _put(p, data=None, headers=None):
        _r = await nexus_call('PUT', f'{_base}{p}', headers={**_h, **(headers or {})}, json=data)
        if not _r['ok']:
            return {'success': False, 'error': _r['body']}
        return _r['json']

    async def _patch(p, data=None, headers=None):
        _r = await nexus_call('PATCH', f'{_base}{p}', headers={**_h, **(headers or {})}, json=data)
        if not _r['ok']:
            return {'success': False, 'error': _r['body']}
        return _r['json'] if _r['content'] else {}

    async def _delete(p, headers=None):
        _r = await nexus_call('DELETE', f'{_base}{p}', headers={**_h, **(headers or {})})
        if not _r['ok']:
            return {'success': False, 'error': _r['body']}
        return _r['json'] if _r['content'] else {}
    '\n    List meetings for a Zoom user.\n\n    Args:\n        auth_info: Dict with access_token for the tool OAuth\n        user_id: Zoom user ID or email. Use "me" for the authenticated user (default)\n        meeting_type: Type of meetings — "scheduled", "live", "upcoming", "upcoming_meetings",\n                      "previous_meetings" (default: "scheduled")\n        page_size: Number of records per page, max 300 (default: 30)\n\n    Returns:\n        list of meeting objects (id, topic, start_time, duration, join_url, etc.)\n    '

    class ZoomCapabilities(NexusCapabilities):
        pass
    meetings = []
    next_page_token = ''
    while True:
        params = {'type': meeting_type, 'page_size': page_size}
        if next_page_token:
            params['next_page_token'] = next_page_token
        response = await _get(f'/users/{user_id}/meetings', params=params)
        meetings.extend(response.get('meetings', []))
        next_page_token = response.get('next_page_token', '')
        if not next_page_token:
            break
    return meetings
