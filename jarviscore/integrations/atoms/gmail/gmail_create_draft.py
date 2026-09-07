async def gmail_create_draft(to: str, subject: str, body: str) -> dict:
    """Create draft via the gmail API."""
    import base64
    _base = 'https://gmail.googleapis.com/gmail/v1/users/me'
    _h = {'Content-Type': 'application/json'}
    raw = f'To: {to}\r\nSubject: {subject}\r\nContent-Type: text/plain; charset=utf-8\r\nMIME-Version: 1.0\r\n\r\n{body}'
    encoded = base64.urlsafe_b64encode(raw.encode()).decode()
    resp = await nexus_call('POST', f'{_base}/drafts', headers=_h, json={'message': {'raw': encoded}})
    if not resp['ok']:
        return {'success': False, 'error': resp['body']}
    data = resp['json']
    return {'success': True, 'draft_id': data.get('id'), 'message_id': data.get('message', {}).get('id')}
