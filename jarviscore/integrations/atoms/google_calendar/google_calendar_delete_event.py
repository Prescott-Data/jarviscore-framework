ATOM_POLICY = {"effect": "destructive", "approval": "required", "idempotency_fields": ["calendar_id", "event_id"], "consequence": "Deletes the calendar event."}

async def google_calendar_delete_event(event_id: str, calendar_id: str='primary') -> dict:
    """Calendar delete event via the google_calendar API."""
    _h = {}
    resp = await nexus_call('DELETE', f'https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events/{event_id}', headers=_h)
    if resp['status_code'] == 204:
        return {'success': True, 'event_id': event_id, 'deleted': True}
    if not resp['ok']:
        return {'success': False, 'error': resp['body']}
    return {'success': True, 'event_id': event_id, 'deleted': True}
