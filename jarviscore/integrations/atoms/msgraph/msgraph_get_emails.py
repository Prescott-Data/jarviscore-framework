async def msgraph_get_emails(max_results: int=20, folder: str='inbox') -> dict:
    """Get emails via the msgraph API."""
    try:
        access_token = _get_nexus_token(None)
    except Exception as e:
        return {'success': False, 'data': None, 'error': f'Auth error: {str(e)}'}
    try:
        resp = await nexus_call('GET', f'https://graph.microsoft.com/v1.0/me/mailFolders/{folder}/messages', headers={'Authorization': f'Bearer {access_token}'}, params={'$top': max_results, '$orderby': 'receivedDateTime desc', '$select': 'id,subject,from,receivedDateTime,isRead,bodyPreview'})
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f"Get emails failed: {resp['status_code']} {resp['body']}"}
        emails = resp['json'].get('value', [])
        return {'success': True, 'data': {'emails': emails, 'count': len(emails)}, 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
