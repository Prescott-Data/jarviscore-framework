async def webex_get_rooms(max_results: int=50) -> dict:
    """Get rooms. GET https://webexapis.com/v1/rooms"""
    try:
        resp = await nexus_call('GET', 'https://webexapis.com/v1/rooms', params={'max': max_results})
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f"Get rooms failed: {resp['status_code']} {resp['body']}"}
        rooms = resp['json'].get('items', [])
        return {'success': True, 'data': {'rooms': rooms, 'count': len(rooms)}, 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
