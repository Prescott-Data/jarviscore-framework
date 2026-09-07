async def msgraph_delete_event(event_id: str) -> dict:
    """Delete event via the msgraph API."""
    try:
        access_token = _get_nexus_token(None)
    except Exception as e:
        return {'success': False, 'data': None, 'error': f'Auth error: {str(e)}'}
    try:
        resp = await nexus_call('DELETE', f'https://graph.microsoft.com/v1.0/me/events/{event_id}', headers={'Authorization': f'Bearer {access_token}'})
        if resp['status_code'] != 204:
            return {'success': False, 'data': None, 'error': f'Delete event failed: {resp['status_code']} {resp['body']}'}
        return {'success': True, 'data': {'event_id': event_id, 'deleted': True}, 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
