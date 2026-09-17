async def msgraph_get_events(max_results: int=20, start_datetime: str=None, end_datetime: str=None) -> dict:
    """Get events. GET https://graph.microsoft.com/v1.0/me/events"""
    try:
        params = {'$top': max_results, '$orderby': 'start/dateTime', '$select': 'id,subject,start,end,location,organizer,isOnlineMeeting'}
        if start_datetime and end_datetime:
            params['$filter'] = f"start/dateTime ge '{start_datetime}' and end/dateTime le '{end_datetime}'"
        resp = await nexus_call('GET', 'https://graph.microsoft.com/v1.0/me/events', headers={'Prefer': 'outlook.timezone="UTC"'}, params=params)
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f"Get events failed: {resp['status_code']} {resp['body']}"}
        events = resp['json'].get('value', [])
        return {'success': True, 'data': {'events': events, 'count': len(events)}, 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
