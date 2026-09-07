async def msgraph_get_teams() -> dict:
    """Get teams. GET https://graph.microsoft.com/v1.0/me/joinedTeams"""
    try:
        access_token = _get_nexus_token(None)
    except Exception as e:
        return {'success': False, 'data': None, 'error': f'Auth error: {str(e)}'}
    try:
        resp = await nexus_call('GET', 'https://graph.microsoft.com/v1.0/me/joinedTeams', headers={'Authorization': f'Bearer {access_token}'})
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f'Get teams failed: {resp['status_code']} {resp['body']}'}
        teams = resp['json'].get('value', [])
        return {'success': True, 'data': {'teams': teams, 'count': len(teams)}, 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
