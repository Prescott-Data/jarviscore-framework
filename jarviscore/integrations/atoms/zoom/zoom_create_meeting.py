async def zoom_create_meeting(topic: str, start_time: str, duration: int, user_id: str='me', agenda: str='', timezone: str='UTC', meeting_type: int=2) -> dict:
    """Create meeting via the zoom API."""
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
    '\n    Create a Zoom meeting.\n\n    Args:\n        auth_info: Dict with access_token for the tool OAuth\n        topic: Meeting topic/title\n        start_time: Meeting start time in ISO 8601 format (e.g. "2026-04-01T10:00:00")\n        duration: Meeting duration in minutes\n        user_id: Zoom user ID or email to schedule for. Use "me" for authenticated user (default)\n        agenda: Meeting description/agenda (default: "")\n        timezone: Timezone for the meeting (default: "UTC")\n        meeting_type: 1=instant, 2=scheduled, 3=recurring no fixed time, 8=recurring fixed time (default: 2)\n\n    Returns:\n        dict with created meeting details (id, join_url, start_url, topic, etc.)\n    '

    class ZoomCapabilities(NexusCapabilities):
        pass
    payload = {'topic': topic, 'type': meeting_type, 'start_time': start_time, 'duration': duration, 'timezone': timezone, 'agenda': agenda}
    return await _post(f'/users/{user_id}/meetings', data=payload)
