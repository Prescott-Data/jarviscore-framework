async def msgraph_get_meeting(meeting_id: str) -> dict:
    """Get meeting via the msgraph API."""
    try:
        resp = await nexus_call('GET', f'https://graph.microsoft.com/v1.0/me/onlineMeetings/{meeting_id}')
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f"Get meeting failed: {resp['status_code']} {resp['body']}"}
        return {'success': True, 'data': resp['json'], 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
