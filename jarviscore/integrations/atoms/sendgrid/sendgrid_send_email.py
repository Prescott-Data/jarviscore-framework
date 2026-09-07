async def sendgrid_send_email(to: str, subject: str, body: str, from_email: str='agents@example.com', body_type: str='text/plain') -> dict:
    """Send email. POST https://api.sendgrid.com/v3/mail/send"""
    _h = {'Content-Type': 'application/json'}
    payload = {'personalizations': [{'to': [{'email': to}]}], 'from': {'email': from_email}, 'subject': subject, 'content': [{'type': body_type, 'value': body}]}
    resp = await nexus_call('POST', 'https://api.sendgrid.com/v3/mail/send', headers=_h, json=payload)
    if resp['status_code'] not in (200, 202):
        raise RuntimeError(f"SendGrid error: {resp['status_code']} {resp['body']}")
    return {'success': True, 'to': to, 'subject': subject}
