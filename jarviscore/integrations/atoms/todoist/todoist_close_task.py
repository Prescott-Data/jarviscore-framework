async def todoist_close_task(task_id: str) -> dict:
    """Close task via the todoist API."""
    try:
        access_token = _get_nexus_token(None)
    except Exception as e:
        return {'success': False, 'data': None, 'error': f'Auth error: {str(e)}'}
    try:
        resp = await nexus_call('POST', f'https://api.todoist.com/api/v1/tasks/{task_id}/close', headers={'Authorization': f'Bearer {access_token}'})
        if resp['status_code'] != 204:
            return {'success': False, 'data': None, 'error': f'Close task failed: {resp['status_code']} {resp['body']}'}
        return {'success': True, 'data': {'task_id': task_id, 'closed': True}, 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
