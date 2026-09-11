async def notion_append_blocks(page_id: str, blocks: list) -> dict:
    """Append blocks via the notion API."""
    try:
        resp = await nexus_call('PATCH', f'https://api.notion.com/v1/blocks/{page_id}/children', json={'children': blocks}, headers={'Content-Type': 'application/json', 'Notion-Version': '2022-06-28'})
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f"Append blocks failed: {resp['status_code']} {resp['body']}"}
        return {'success': True, 'data': resp['json'], 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
