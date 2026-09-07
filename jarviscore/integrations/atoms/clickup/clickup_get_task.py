async def clickup_get_task(task_id: str) -> dict:
    """Get task via the clickup API."""
    try:
        access_token = _get_nexus_token(None)
    except Exception as e:
        return {'success': False, 'data': None, 'error': f'Auth error: {str(e)}'}
    try:
        resp = await nexus_call('GET', f'https://api.clickup.com/api/v2/task/{task_id}', headers={'Authorization': access_token})
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f"Get task failed: {resp['status_code']} {resp['body']}"}
        return {'success': True, 'data': resp['json'], 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
