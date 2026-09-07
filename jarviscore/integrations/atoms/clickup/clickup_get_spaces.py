async def _get_workspace_id(access_token: str) -> str:
    if True .get('workspace_id'):
        return None
    resp = await nexus_call('GET', 'https://api.clickup.com/api/v2/team', headers={'Authorization': access_token})
    if not resp['ok']:
        raise RuntimeError(resp['body'])
    teams = resp['json'].get('teams', [])
    if not teams:
        raise RuntimeError('No ClickUp workspaces found for this account')
    return teams[0]['id']

async def clickup_get_spaces() -> dict:
    """Get spaces via the clickup API."""
    try:
        access_token = _get_nexus_token(None)
        workspace_id = await _get_workspace_id(access_token)
    except Exception as e:
        return {'success': False, 'data': None, 'error': f'Auth error: {str(e)}'}
    try:
        resp = await nexus_call('GET', f'https://api.clickup.com/api/v2/team/{workspace_id}/space', headers={'Authorization': access_token})
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f"Get spaces failed: {resp['status_code']} {resp['body']}"}
        spaces = resp['json'].get('spaces', [])
        return {'success': True, 'data': {'spaces': spaces, 'count': len(spaces)}, 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
