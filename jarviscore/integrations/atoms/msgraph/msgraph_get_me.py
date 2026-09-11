async def msgraph_get_me() -> dict:
    """Get me. GET https://graph.microsoft.com/v1.0/me"""
    try:
        resp = await nexus_call('GET', 'https://graph.microsoft.com/v1.0/me')
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f"Get me failed: {resp['status_code']} {resp['body']}"}
        return {'success': True, 'data': resp['json'], 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
