async def notion_get_page(page_id: str) -> dict:
    """Get page via the notion API."""
    try:
        access_token = _get_nexus_token(None)
    except Exception as e:
        return {'success': False, 'data': None, 'error': f'Auth error: {str(e)}'}
    try:
        resp = await nexus_call('GET', f'https://api.notion.com/v1/pages/{page_id}', headers={'Authorization': f'Bearer {access_token}', 'Notion-Version': '2022-06-28'})
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f'Get page failed: {resp['status_code']} {resp['body']}'}
        return {'success': True, 'data': resp['json'], 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
