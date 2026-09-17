async def brevo_send_email(to: str, subject: str, body: str, from_email: str='agents@example.com', from_name: str='AI Agent') -> dict:
    """Send email. POST https://api.brevo.com/v3/smtp/email"""
    _h = {'Content-Type': 'application/json'}
    payload = {'sender': {'name': from_name, 'email': from_email}, 'to': [{'email': to}], 'subject': subject, 'textContent': body}
    resp = await nexus_call('POST', 'https://api.brevo.com/v3/smtp/email', headers=_h, json=payload)
    if not resp['ok']:
        return {'success': False, 'error': resp['body']}
    data = resp['json']
    return {'success': True, 'message_id': data.get('messageId'), 'to': to}
