async def msgraph_get_chats(max_results: int=20) -> dict:
    """Get chats. GET https://graph.microsoft.com/v1.0/me/chats"""
    try:
        access_token = _get_nexus_token(None)
    except Exception as e:
        return {'success': False, 'data': None, 'error': f'Auth error: {str(e)}'}
    try:
        resp = await nexus_call('GET', 'https://graph.microsoft.com/v1.0/me/chats', headers={'Authorization': f'Bearer {access_token}'}, params={'$top': max_results, '$expand': 'members'})
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f"Get chats failed: {resp['status_code']} {resp['body']}"}
        chats = resp['json'].get('value', [])
        return {'success': True, 'data': {'chats': chats, 'count': len(chats)}, 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
