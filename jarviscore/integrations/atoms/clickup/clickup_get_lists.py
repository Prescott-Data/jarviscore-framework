async def clickup_get_lists(space_id: str) -> dict:
    """Get lists via the clickup API."""
    try:
        resp = await nexus_call('GET', f'https://api.clickup.com/api/v2/space/{space_id}/list')
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f"Get lists failed: {resp['status_code']} {resp['body']}"}
        lists = resp['json'].get('lists', [])
        return {'success': True, 'data': {'lists': lists, 'count': len(lists)}, 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
