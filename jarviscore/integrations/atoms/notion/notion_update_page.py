async def notion_update_page(page_id: str, title: str=None, archived: bool=None) -> dict:
    """Update page via the notion API."""
    try:
        payload = {}
        if title is not None:
            payload['properties'] = {'title': {'title': [{'type': 'text', 'text': {'content': title}}]}}
        if archived is not None:
            payload['archived'] = archived
        resp = await nexus_call('PATCH', f'https://api.notion.com/v1/pages/{page_id}', json=payload, headers={'Content-Type': 'application/json', 'Notion-Version': '2022-06-28'})
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f"Update page failed: {resp['status_code']} {resp['body']}"}
        return {'success': True, 'data': resp['json'], 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
