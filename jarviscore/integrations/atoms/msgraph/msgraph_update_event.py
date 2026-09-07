async def msgraph_update_event(event_id: str, subject: str=None, start_datetime: str=None, end_datetime: str=None, timezone: str='UTC', body: str=None, location: str=None) -> dict:
    """Update event via the msgraph API."""
    try:
        access_token = _get_nexus_token(None)
    except Exception as e:
        return {'success': False, 'data': None, 'error': f'Auth error: {str(e)}'}
    try:
        payload = {}
        if subject:
            payload['subject'] = subject
        if start_datetime:
            payload['start'] = {'dateTime': start_datetime, 'timeZone': timezone}
        if end_datetime:
            payload['end'] = {'dateTime': end_datetime, 'timeZone': timezone}
        if body:
            payload['body'] = {'contentType': 'Text', 'content': body}
        if location:
            payload['location'] = {'displayName': location}
        resp = await nexus_call('PATCH', f'https://graph.microsoft.com/v1.0/me/events/{event_id}', headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'}, json=payload)
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f'Update event failed: {resp['status_code']} {resp['body']}'}
        return {'success': True, 'data': resp['json'], 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
