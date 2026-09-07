async def discord_get_guilds() -> dict:
    """Get guilds. GET https://discord.com/api/v10/users/@me/guilds"""
    try:
        access_token = _get_nexus_token(None)
    except Exception as e:
        return {'success': False, 'data': None, 'error': f'Auth error: {str(e)}'}
    try:
        resp = await nexus_call('GET', 'https://discord.com/api/v10/users/@me/guilds', headers={'Authorization': f'Bearer {access_token}'})
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f'Get guilds failed: {resp['status_code']} {resp['body']}'}
        guilds = resp['json']
        return {'success': True, 'data': {'guilds': guilds, 'count': len(guilds)}, 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
