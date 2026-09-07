async def clickup_create_task(list_id: str, name: str, description: str=None, priority: int=None, status: str=None) -> dict:
    """Create task via the clickup API."""
    try:
        access_token = _get_nexus_token(None)
    except Exception as e:
        return {'success': False, 'data': None, 'error': f'Auth error: {str(e)}'}
    try:
        payload = {'name': name}
        if description:
            payload['description'] = description
        if priority:
            payload['priority'] = priority
        if status:
            payload['status'] = status
        resp = await nexus_call('POST', f'https://api.clickup.com/api/v2/list/{list_id}/task', json=payload, headers={'Authorization': access_token, 'Content-Type': 'application/json'})
        if resp['status_code'] not in (200, 201):
            return {'success': False, 'data': None, 'error': f'Create task failed: {resp['status_code']} {resp['body']}'}
        return {'success': True, 'data': resp['json'], 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
