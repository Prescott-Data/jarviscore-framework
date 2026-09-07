async def clickup_create_comment(task_id: str, comment_text: str) -> dict:
    """Create comment via the clickup API."""
    try:
        access_token = _get_nexus_token(None)
    except Exception as e:
        return {'success': False, 'data': None, 'error': f'Auth error: {str(e)}'}
    try:
        resp = await nexus_call('POST', f'https://api.clickup.com/api/v2/task/{task_id}/comment', json={'comment_text': comment_text}, headers={'Authorization': access_token, 'Content-Type': 'application/json'})
        if resp['status_code'] not in (200, 201):
            return {'success': False, 'data': None, 'error': f"Create comment failed: {resp['status_code']} {resp['body']}"}
        return {'success': True, 'data': resp['json'], 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
