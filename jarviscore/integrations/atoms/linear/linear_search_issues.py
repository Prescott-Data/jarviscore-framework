async def linear_search_issues(query: str, max_results: int=20) -> dict:
    """Search issues. POST https://api.linear.app/graphql"""
    try:
        access_token = _get_nexus_token(None)
    except Exception as e:
        return {'success': False, 'data': None, 'error': f'Auth error: {str(e)}'}
    gql = '\n    query($term: String!, $first: Int!) {\n        issues(filter: { title: { containsIgnoreCase: $term } }, first: $first) {\n            nodes {\n                id\n                identifier\n                title\n                priority\n                state {\n                    name\n                }\n                assignee {\n                    name\n                }\n                team {\n                    name\n                    key\n                }\n                createdAt\n            }\n        }\n    }\n    '
    try:
        resp = await nexus_call('POST', 'https://api.linear.app/graphql', json={'query': gql, 'variables': {'term': query, 'first': max_results}}, headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'})
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f"Search issues failed: {resp['status_code']} {resp['body']}"}
        data = resp['json']
        if 'errors' in data:
            return {'success': False, 'data': None, 'error': str(data['errors'])}
        issues = data['data']['issues']['nodes']
        return {'success': True, 'data': {'issues': issues, 'count': len(issues)}, 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
