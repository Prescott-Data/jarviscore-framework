async def linear_get_issues(team_id: str=None, max_results: int=50) -> dict:
    """Get issues. POST https://api.linear.app/graphql"""
    try:
        access_token = _get_nexus_token(None)
    except Exception as e:
        return {'success': False, 'data': None, 'error': f'Auth error: {str(e)}'}
    filter_clause = f'filter: {{ team: {{ id: {{ eq: "{team_id}" }} }} }},' if team_id else ''
    query = f'\n    query {{\n        issues({filter_clause} first: {max_results}) {{\n            nodes {{\n                id\n                identifier\n                title\n                description\n                priority\n                state {{\n                    name\n                }}\n                assignee {{\n                    name\n                }}\n                createdAt\n                updatedAt\n            }}\n        }}\n    }}\n    '
    try:
        resp = await nexus_call('POST', 'https://api.linear.app/graphql', json={'query': query}, headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'})
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f"Get issues failed: {resp['status_code']} {resp['body']}"}
        data = resp['json']
        if 'errors' in data:
            return {'success': False, 'data': None, 'error': str(data['errors'])}
        issues = data['data']['issues']['nodes']
        return {'success': True, 'data': {'issues': issues, 'count': len(issues)}, 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
