import hashlib
import re

ATOM_POLICY = {
    "effect": "write",
    "approval": "never",
    "idempotency_fields": [
        "summary", "start_datetime", "end_datetime", "calendar_id", "attendees", "video_call",
        "recurrence",
    ],
    "consequence": "Creates one Google Calendar event; guests are emailed the invitation.",
}


async def google_calendar_create_event(summary: str, start_datetime: str, end_datetime: str, description: str='', location: str='', attendees: list=None, calendar_id: str='primary', video_call: bool=False, time_zone: str='', recurrence: list=None, reminder_minutes: list=None) -> dict:
    """Create one Google Calendar event; guests in `attendees` are emailed the invitation.
    POST https://developers.google.com/workspace/calendar/api/v3/reference/events/insert
    `start_datetime` and `end_datetime` are full times with their UTC offset
    (2026-11-24T11:30:00-05:00). For an all-day event pass dates instead (2026-11-24):
    `end_datetime` is then the day AFTER the last day, so one day is 2026-11-24 to
    2026-11-25 and Monday to Wednesday is the Monday to the Thursday.
    `video_call` true adds a Google Meet link to the event, made by Google and returned as
    `meet_link`; it is in the invitation the guests receive.
    `time_zone` is the IANA zone the event is shown in (America/New_York); leave it out and
    the times' own offset stands. A time with no offset needs it, and so does an event
    that repeats.
    `recurrence` makes the event repeat: a list of RFC 5545 rules, such as
    ["RRULE:FREQ=WEEKLY;BYDAY=TU;COUNT=10"] (every Tuesday, ten times) or
    ["RRULE:FREQ=MONTHLY;BYMONTHDAY=1"]; the start and end are the first occurrence's.
    `reminder_minutes` sets pop-up reminders that many minutes before ([10, 60]); left out,
    the calendar's own defaults apply; [] means none.
    This does not check that the time is free."""
    _h = {'Content-Type': 'application/json'}
    zone = str(time_zone or '').strip()
    first, last = str(start_datetime or '').strip(), str(end_datetime or '').strip()
    dated = [bool(re.match(r'^\d{4}-\d{2}-\d{2}$', moment)) for moment in (first, last)]
    if dated[0] != dated[1]:
        return {'success': False, 'error': 'start_datetime and end_datetime must both be dates (an all-day event) or both be times'}
    rules = [str(rule).strip() for rule in (recurrence or []) if str(rule).strip()]
    if dated[0]:
        if last <= first:
            return {'success': False, 'error': 'an all-day event ends the day after its last day: end_datetime must be later than start_datetime'}
        start, end = {'date': first}, {'date': last}
    else:
        start, end = {'dateTime': first}, {'dateTime': last}
        for moment in (start, end):
            # A time that carries its offset needs no zone; one that does not is read in
            # the zone given. No zone is assumed: a guessed zone is a meeting at the wrong hour.
            offset = re.search(r'(Z|[+-]\d{2}:?\d{2})$', moment['dateTime'])
            if not offset and not zone:
                return {'success': False, 'error': f"{moment['dateTime']!r} has no UTC offset: pass the time with its offset (2026-11-24T11:30:00-05:00) or name the zone in time_zone"}
            if zone:
                moment['timeZone'] = zone
        if rules and not zone:
            return {'success': False, 'error': 'an event that repeats needs time_zone (the IANA zone its times are in), so it keeps its hour when the clocks change'}
    bad = [rule for rule in rules if not re.match(r'^(RRULE|EXRULE|RDATE|EXDATE)[:;]', rule)]
    if bad:
        return {'success': False, 'error': f'not a recurrence rule (RRULE:FREQ=WEEKLY;BYDAY=TU): {bad[0]!r}'}
    payload = {'summary': summary, 'description': description, 'location': location, 'start': start, 'end': end}
    if rules:
        payload['recurrence'] = rules
    if reminder_minutes is not None:
        payload['reminders'] = {'useDefault': False, 'overrides': [{'method': 'popup', 'minutes': int(minutes)} for minutes in reminder_minutes]}
    params = {}
    if attendees:
        payload['attendees'] = [{'email': e} for e in attendees]
        # Google emails guests only when asked: without sendUpdates the event lands on their
        # calendars silently and nobody gets the invitation.
        params['sendUpdates'] = 'all'
    if video_call is True:
        # Google makes the Meet link when the event asks for one and the request says it
        # carries conference data. The request id is the same for the same event, so a call
        # made again does not ask for a second link.
        seed = f'{calendar_id}|{summary}|{start_datetime}|{end_datetime}'
        payload['conferenceData'] = {'createRequest': {
            'requestId': hashlib.sha1(seed.encode()).hexdigest()[:32],
            'conferenceSolutionKey': {'type': 'hangoutsMeet'},
        }}
        params['conferenceDataVersion'] = 1
    resp = await nexus_call('POST', f'https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events', headers=_h, params=params, json=payload)
    if not resp['ok']:
        return {'success': False, 'error': resp['body']}
    data = resp['json']
    result = {
        'success': True,
        'event_id': data.get('id'),
        'html_link': data.get('htmlLink'),
        'summary': summary,
        'starts_at': start_datetime,
        'ends_at': end_datetime,
        'all_day': dated[0],
        'attendees': list(attendees or []),
        'calendar_id': calendar_id,
    }
    if rules:
        result['recurrence'] = data.get('recurrence') or rules
    if video_call is True:
        entries = (data.get('conferenceData') or {}).get('entryPoints') or []
        link = data.get('hangoutLink') or next(
            (e.get('uri') for e in entries if isinstance(e, dict) and e.get('entryPointType') == 'video'), None)
        result['meet_link'] = link
        if not link:
            result['note'] = ('The event was created, but Google returned no Meet link yet; '
                              'open the event to check before telling anyone it has one.')
    return result
