async def zoom_update_meeting(meeting_id: str, topic: str=None, start_time: str=None, duration: int=None, agenda: str=None, timezone: str=None) -> dict:
    """Update meeting via the zoom API."""
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
    '\n    Update a Zoom meeting.\n\n    Args:\n        auth_info: Dict with access_token for the tool OAuth\n        meeting_id: The meeting ID to update\n        topic: New meeting topic (optional)\n        start_time: New start time in ISO 8601 format (optional)\n        duration: New duration in minutes (optional)\n        agenda: New agenda/description (optional)\n        timezone: New timezone (optional)\n\n    Returns:\n        dict with {"updated": True} on success\n    '

    class ZoomCapabilities(NexusCapabilities):
        pass
    payload = {}
    if topic is not None:
        payload['topic'] = topic
    if start_time is not None:
        payload['start_time'] = start_time
    if duration is not None:
        payload['duration'] = duration
    if agenda is not None:
        payload['agenda'] = agenda
    if timezone is not None:
        payload['timezone'] = timezone
    await _patch(f'/meetings/{meeting_id}', data=payload)
    return {'updated': True, 'meeting_id': meeting_id}
