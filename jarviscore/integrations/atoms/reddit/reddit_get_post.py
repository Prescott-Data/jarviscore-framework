async def reddit_get_post(post_id: str) -> dict:
    """Get post via the reddit API."""
    try:
        access_token = _get_nexus_token(None)
    except Exception as e:
        return {'success': False, 'data': None, 'error': f'Auth error: {str(e)}'}
    try:
        clean_id = post_id.replace('t3_', '')
        resp = await nexus_call('GET', f'https://oauth.reddit.com/api/info', params={'id': f't3_{clean_id}'}, headers={'Authorization': f'Bearer {access_token}', 'User-Agent': 'jarviscore/1.0'})
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f'Get post failed: {resp['status_code']} {resp['body']}'}
        children = resp['json'].get('data', {}).get('children', [])
        if not children:
            return {'success': False, 'data': None, 'error': 'Post not found'}
        return {'success': True, 'data': children[0].get('data'), 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
