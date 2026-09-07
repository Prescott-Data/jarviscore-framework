async def webex_get_room(room_id: str) -> dict:
    """Get room via the webex API."""
    try:
        access_token = _get_nexus_token(None)
    except Exception as e:
        return {'success': False, 'data': None, 'error': f'Auth error: {str(e)}'}
    try:
        resp = await nexus_call('GET', f'https://webexapis.com/v1/rooms/{room_id}', headers={'Authorization': f'Bearer {access_token}'})
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f'Get room failed: {resp['status_code']} {resp['body']}'}
        return {'success': True, 'data': resp['json'], 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
