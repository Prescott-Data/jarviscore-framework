async def msgraph_send_email(to: list, subject: str, body: str, body_type: str='Text', cc: list=None) -> dict:
    """Send email. POST https://graph.microsoft.com/v1.0/me/sendMail"""
    try:
        access_token = _get_nexus_token(None)
    except Exception as e:
        return {'success': False, 'data': None, 'error': f'Auth error: {str(e)}'}
    try:
        to_recipients = [{'emailAddress': {'address': addr}} for addr in to]
        payload = {'message': {'subject': subject, 'body': {'contentType': body_type, 'content': body}, 'toRecipients': to_recipients}}
        if cc:
            payload['message']['ccRecipients'] = [{'emailAddress': {'address': addr}} for addr in cc]
        resp = await nexus_call('POST', 'https://graph.microsoft.com/v1.0/me/sendMail', headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'}, json=payload)
        if resp['status_code'] != 202:
            return {'success': False, 'data': None, 'error': f'Send email failed: {resp['status_code']} {resp['body']}'}
        return {'success': True, 'data': {'sent': True, 'to': to, 'subject': subject}, 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
