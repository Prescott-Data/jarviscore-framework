async def linear_get_issue(issue_id: str) -> dict:
    """Get issue. POST https://api.linear.app/graphql"""
    query = '\n    query($id: String!) {\n        issue(id: $id) {\n            id\n            identifier\n            title\n            description\n            priority\n            state {\n                name\n            }\n            assignee {\n                name\n                email\n            }\n            team {\n                name\n                key\n            }\n            labels {\n                nodes {\n                    name\n                }\n            }\n            createdAt\n            updatedAt\n        }\n    }\n    '
    try:
        resp = await nexus_call('POST', 'https://api.linear.app/graphql', json={'query': query, 'variables': {'id': issue_id}}, headers={'Content-Type': 'application/json'})
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f"Get issue failed: {resp['status_code']} {resp['body']}"}
        data = resp['json']
        if 'errors' in data:
            return {'success': False, 'data': None, 'error': str(data['errors'])}
        return {'success': True, 'data': data['data']['issue'], 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
