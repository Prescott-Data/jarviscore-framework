async def discord_get_connections() -> dict:
    """Get connections. GET https://discord.com/api/v10/users/@me/connections"""
    try:
        resp = await nexus_call('GET', 'https://discord.com/api/v10/users/@me/connections')
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f"Get connections failed: {resp['status_code']} {resp['body']}"}
        connections = resp['json']
        return {'success': True, 'data': {'connections': connections, 'count': len(connections)}, 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
