async def msgraph_create_event(subject: str, start_datetime: str, end_datetime: str, timezone: str='UTC', attendees: list=None, body: str=None, location: str=None) -> dict:
    """Create event. POST https://graph.microsoft.com/v1.0/me/events"""
    try:
        payload = {'subject': subject, 'start': {'dateTime': start_datetime, 'timeZone': timezone}, 'end': {'dateTime': end_datetime, 'timeZone': timezone}}
        if attendees:
            payload['attendees'] = [{'emailAddress': {'address': a}, 'type': 'required'} for a in attendees]
        if body:
            payload['body'] = {'contentType': 'Text', 'content': body}
        if location:
            payload['location'] = {'displayName': location}
        resp = await nexus_call('POST', 'https://graph.microsoft.com/v1.0/me/events', headers={'Content-Type': 'application/json'}, json=payload)
        if resp['status_code'] != 201:
            return {'success': False, 'data': None, 'error': f"Create event failed: {resp['status_code']} {resp['body']}"}
        return {'success': True, 'data': resp['json'], 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
