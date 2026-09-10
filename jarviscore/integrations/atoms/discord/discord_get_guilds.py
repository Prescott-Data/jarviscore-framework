async def discord_get_guilds() -> dict:
    """Get guilds. GET https://discord.com/api/v10/users/@me/guilds"""
    try:
        resp = await nexus_call('GET', 'https://discord.com/api/v10/users/@me/guilds')
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f"Get guilds failed: {resp['status_code']} {resp['body']}"}
        guilds = resp['json']
        return {'success': True, 'data': {'guilds': guilds, 'count': len(guilds)}, 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
