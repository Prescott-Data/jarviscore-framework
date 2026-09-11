ATOM_POLICY = {
    "effect": "write",
    "approval": "never",
    "idempotency_fields": ["summary", "start_datetime", "end_datetime", "calendar_id"],
    "consequence": "Creates one Google Calendar event in the selected free slot.",
}


async def google_calendar_create_event(summary: str, start_datetime: str, end_datetime: str, description: str='', location: str='', attendees: list=None, calendar_id: str='primary') -> dict:
    """Calendar create event via the google_calendar API."""
    _h = {'Content-Type': 'application/json'}
    payload = {'summary': summary, 'description': description, 'location': location, 'start': {'dateTime': start_datetime, 'timeZone': 'Africa/Nairobi'}, 'end': {'dateTime': end_datetime, 'timeZone': 'Africa/Nairobi'}}
    if attendees:
        payload['attendees'] = [{'email': e} for e in attendees]
    resp = await nexus_call('POST', f'https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events', headers=_h, json=payload)
    if not resp['ok']:
        return {'success': False, 'error': resp['body']}
    data = resp['json']
    return {
        'success': True,
        'event_id': data.get('id'),
        'html_link': data.get('htmlLink'),
        'summary': summary,
        'starts_at': start_datetime,
        'ends_at': end_datetime,
        'attendees': list(attendees or []),
        'calendar_id': calendar_id,
    }
