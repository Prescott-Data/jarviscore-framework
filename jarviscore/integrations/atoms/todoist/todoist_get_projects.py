async def todoist_get_projects() -> dict:
    """Get projects. GET https://api.todoist.com/api/v1/projects"""
    try:
        access_token = _get_nexus_token(None)
    except Exception as e:
        return {'success': False, 'data': None, 'error': f'Auth error: {str(e)}'}
    try:
        resp = await nexus_call('GET', 'https://api.todoist.com/api/v1/projects', headers={'Authorization': f'Bearer {access_token}'})
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f"Get projects failed: {resp['status_code']} {resp['body']}"}
        projects = resp['json'].get('results', [])
        return {'success': True, 'data': {'projects': projects, 'count': len(projects)}, 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
