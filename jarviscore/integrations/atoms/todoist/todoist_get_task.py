async def todoist_get_task(task_id: str) -> dict:
    """Get task via the todoist API."""
    try:
        resp = await nexus_call('GET', f'https://api.todoist.com/api/v1/tasks/{task_id}')
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f"Get task failed: {resp['status_code']} {resp['body']}"}
        data = resp['json']
        return {'success': True, 'data': data.get('results', data), 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
