async def msgraph_get_channels(team_id: str) -> dict:
    """Get channels via the msgraph API."""
    try:
        resp = await nexus_call('GET', f'https://graph.microsoft.com/v1.0/teams/{team_id}/channels')
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f"Get channels failed: {resp['status_code']} {resp['body']}"}
        channels = resp['json'].get('value', [])
        return {'success': True, 'data': {'channels': channels, 'count': len(channels)}, 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
