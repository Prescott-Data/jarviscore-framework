async def todoist_update_task(task_id: str, content: str=None, due_string: str=None, priority: int=None) -> dict:
    """Update task via the todoist API."""
    try:
        access_token = _get_nexus_token(None)
    except Exception as e:
        return {'success': False, 'data': None, 'error': f'Auth error: {str(e)}'}
    try:
        payload = {}
        if content:
            payload['content'] = content
        if due_string:
            payload['due_string'] = due_string
        if priority:
            payload['priority'] = priority
        resp = await nexus_call('POST', f'https://api.todoist.com/api/v1/tasks/{task_id}', json=payload, headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'})
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f'Update task failed: {resp['status_code']} {resp['body']}'}
        data = resp['json']
        return {'success': True, 'data': data.get('results', data), 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
