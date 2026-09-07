async def notion_search(query: str, filter_type: str=None) -> dict:
    """Search. POST https://api.notion.com/v1/search"""
    try:
        access_token = _get_nexus_token(None)
    except Exception as e:
        return {'success': False, 'data': None, 'error': f'Auth error: {str(e)}'}
    try:
        payload = {'query': query}
        if filter_type in ('page', 'database'):
            payload['filter'] = {'value': filter_type, 'property': 'object'}
        resp = await nexus_call('POST', 'https://api.notion.com/v1/search', json=payload, headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json', 'Notion-Version': '2022-06-28'})
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f'Search failed: {resp['status_code']} {resp['body']}'}
        results = resp['json'].get('results', [])
        return {'success': True, 'data': {'results': results, 'count': len(results)}, 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
