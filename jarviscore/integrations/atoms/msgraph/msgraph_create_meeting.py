async def msgraph_create_meeting(subject: str, start_datetime: str, end_datetime: str, timezone: str='UTC', participants: list=None) -> dict:
    """Create meeting. POST https://graph.microsoft.com/v1.0/me/onlineMeetings"""
    try:
        access_token = _get_nexus_token(None)
    except Exception as e:
        return {'success': False, 'data': None, 'error': f'Auth error: {str(e)}'}
    try:
        payload = {'subject': subject, 'startDateTime': f'{start_datetime}', 'endDateTime': f'{end_datetime}'}
        if participants:
            payload['participants'] = {'attendees': [{'upn': p} for p in participants]}
        resp = await nexus_call('POST', 'https://graph.microsoft.com/v1.0/me/onlineMeetings', headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'}, json=payload)
        if resp['status_code'] != 201:
            return {'success': False, 'data': None, 'error': f"Create meeting failed: {resp['status_code']} {resp['body']}"}
        data = resp['json']
        return {'success': True, 'data': {'meeting_id': data.get('id'), 'join_url': data.get('joinWebUrl'), 'subject': data.get('subject')}, 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
