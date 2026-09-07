async def notion_create_page(parent_id: str, title: str, parent_type: str='page') -> dict:
    """Create page. POST https://api.notion.com/v1/pages"""
    try:
        access_token = _get_nexus_token(None)
    except Exception as e:
        return {'success': False, 'data': None, 'error': f'Auth error: {str(e)}'}
    try:
        if parent_type == 'database':
            parent = {'database_id': parent_id}
        else:
            parent = {'page_id': parent_id}
        resp = await nexus_call('POST', 'https://api.notion.com/v1/pages', json={'parent': parent, 'properties': {'title': {'title': [{'type': 'text', 'text': {'content': title}}]}}}, headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json', 'Notion-Version': '2022-06-28'})
        if resp['status_code'] not in (200, 201):
            return {'success': False, 'data': None, 'error': f'Create page failed: {resp['status_code']} {resp['body']}'}
        return {'success': True, 'data': resp['json'], 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
