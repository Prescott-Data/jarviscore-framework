async def linear_get_me() -> dict:
    """Get me. POST https://api.linear.app/graphql"""
    try:
        access_token = _get_nexus_token(None)
    except Exception as e:
        return {'success': False, 'data': None, 'error': f'Auth error: {str(e)}'}
    query = '\n    query {\n        viewer {\n            id\n            name\n            email\n            displayName\n            avatarUrl\n            createdAt\n        }\n    }\n    '
    try:
        resp = await nexus_call('POST', 'https://api.linear.app/graphql', json={'query': query}, headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'})
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f'Get me failed: {resp['status_code']} {resp['body']}'}
        data = resp['json']
        if 'errors' in data:
            return {'success': False, 'data': None, 'error': str(data['errors'])}
        return {'success': True, 'data': data['data']['viewer'], 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
