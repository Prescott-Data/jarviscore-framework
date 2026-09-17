async def notion_get_blocks(page_id: str) -> dict:
    """Get blocks via the notion API."""
    try:
        blocks = []
        url = f'https://api.notion.com/v1/blocks/{page_id}/children'
        headers = {'Notion-Version': '2022-06-28'}
        while url:
            resp = await nexus_call('GET', url, headers=headers)
            if resp['status_code'] != 200:
                return {'success': False, 'data': None, 'error': f"Get blocks failed: {resp['status_code']} {resp['body']}"}
            result = resp['json']
            blocks.extend(result.get('results', []))
            url = None
            if result.get('has_more') and result.get('next_cursor'):
                url = f"https://api.notion.com/v1/blocks/{page_id}/children?start_cursor={result['next_cursor']}"
        return {'success': True, 'data': {'blocks': blocks, 'count': len(blocks)}, 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
