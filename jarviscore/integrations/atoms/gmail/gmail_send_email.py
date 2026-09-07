async def gmail_send_email(to: str, subject: str, body: str, body_type: str='text/plain') -> dict:
    """Send email via the gmail API."""
    import base64, json
    _base = 'https://gmail.googleapis.com/gmail/v1/users/me'
    _h = {'Content-Type': 'application/json'}
    raw = f'To: {to}\r\nSubject: {subject}\r\nContent-Type: {body_type}; charset=utf-8\r\nMIME-Version: 1.0\r\n\r\n{body}'
    encoded = base64.urlsafe_b64encode(raw.encode()).decode()
    resp = await nexus_call('POST', f'{_base}/messages/send', headers=_h, json={'raw': encoded})
    if not resp['ok']:
        return {'success': False, 'error': resp['body']}
    data = resp['json']
    return {'success': True, 'message_id': data.get('id'), 'thread_id': data.get('threadId')}
