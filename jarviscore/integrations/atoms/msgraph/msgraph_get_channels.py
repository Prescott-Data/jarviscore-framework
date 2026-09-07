async def msgraph_get_channels(team_id: str) -> dict:
    """Get channels via the msgraph API."""
    try:
        access_token = _get_nexus_token(None)
    except Exception as e:
        return {'success': False, 'data': None, 'error': f'Auth error: {str(e)}'}
    try:
        resp = await nexus_call('GET', f'https://graph.microsoft.com/v1.0/teams/{team_id}/channels', headers={'Authorization': f'Bearer {access_token}'})
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f'Get channels failed: {resp['status_code']} {resp['body']}'}
        channels = resp['json'].get('value', [])
        return {'success': True, 'data': {'channels': channels, 'count': len(channels)}, 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
