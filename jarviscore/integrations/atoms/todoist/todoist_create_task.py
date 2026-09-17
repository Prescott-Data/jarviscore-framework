async def todoist_create_task(content: str, project_id: str=None, due_string: str=None, priority: int=1) -> dict:
    """Create task. POST https://api.todoist.com/api/v1/tasks"""
    try:
        payload = {'content': content, 'priority': priority}
        if project_id:
            payload['project_id'] = project_id
        if due_string:
            payload['due_string'] = due_string
        resp = await nexus_call('POST', 'https://api.todoist.com/api/v1/tasks', json=payload, headers={'Content-Type': 'application/json'})
        if resp['status_code'] not in (200, 201):
            return {'success': False, 'data': None, 'error': f"Create task failed: {resp['status_code']} {resp['body']}"}
        return {'success': True, 'data': resp['json'].get('results', resp['json']), 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
