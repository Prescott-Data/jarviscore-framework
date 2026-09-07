async def clickup_update_task(task_id: str, name: str=None, description: str=None, status: str=None, priority: int=None) -> dict:
    """Update task via the clickup API."""
    try:
        access_token = _get_nexus_token(None)
    except Exception as e:
        return {'success': False, 'data': None, 'error': f'Auth error: {str(e)}'}
    try:
        payload = {}
        if name:
            payload['name'] = name
        if description:
            payload['description'] = description
        if status:
            payload['status'] = status
        if priority:
            payload['priority'] = priority
        resp = await nexus_call('PUT', f'https://api.clickup.com/api/v2/task/{task_id}', json=payload, headers={'Authorization': access_token, 'Content-Type': 'application/json'})
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f'Update task failed: {resp['status_code']} {resp['body']}'}
        return {'success': True, 'data': resp['json'], 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
