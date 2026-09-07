async def webex_get_messages(room_id: str, max_results: int=50) -> dict:
    """Get messages. GET https://webexapis.com/v1/messages"""
    try:
        access_token = _get_nexus_token(None)
    except Exception as e:
        return {'success': False, 'data': None, 'error': f'Auth error: {str(e)}'}
    try:
        resp = await nexus_call('GET', 'https://webexapis.com/v1/messages', headers={'Authorization': f'Bearer {access_token}'}, params={'roomId': room_id, 'max': max_results})
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f'Get messages failed: {resp['status_code']} {resp['body']}'}
        messages = resp['json'].get('items', [])
        return {'success': True, 'data': {'messages': messages, 'count': len(messages)}, 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
