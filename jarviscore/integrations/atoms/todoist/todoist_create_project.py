async def todoist_create_project(name: str, color: str=None, is_favorite: bool=False) -> dict:
    """Create project. POST https://api.todoist.com/api/v1/projects"""
    try:
        payload = {'name': name, 'is_favorite': is_favorite}
        if color:
            payload['color'] = color
        resp = await nexus_call('POST', 'https://api.todoist.com/api/v1/projects', json=payload, headers={'Content-Type': 'application/json'})
        if resp['status_code'] not in (200, 201):
            return {'success': False, 'data': None, 'error': f"Create project failed: {resp['status_code']} {resp['body']}"}
        data = resp['json']
        return {'success': True, 'data': data.get('results', data), 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
