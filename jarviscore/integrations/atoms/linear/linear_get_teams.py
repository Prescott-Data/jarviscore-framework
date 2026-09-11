async def linear_get_teams() -> dict:
    """Get teams. POST https://api.linear.app/graphql"""
    query = '\n    query {\n        teams {\n            nodes {\n                id\n                name\n                key\n                description\n                issueCount\n                createdAt\n            }\n        }\n    }\n    '
    try:
        resp = await nexus_call('POST', 'https://api.linear.app/graphql', json={'query': query}, headers={'Content-Type': 'application/json'})
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f"Get teams failed: {resp['status_code']} {resp['body']}"}
        data = resp['json']
        if 'errors' in data:
            return {'success': False, 'data': None, 'error': str(data['errors'])}
        teams = data['data']['teams']['nodes']
        return {'success': True, 'data': {'teams': teams, 'count': len(teams)}, 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
