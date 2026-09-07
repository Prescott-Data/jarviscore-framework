async def reddit_submit_comment(parent_id: str, text: str) -> dict:
    """Submit comment. POST https://oauth.reddit.com/api/comment"""
    try:
        access_token = _get_nexus_token(None)
    except Exception as e:
        return {'success': False, 'data': None, 'error': f'Auth error: {str(e)}'}
    try:
        resp = await nexus_call('POST', 'https://oauth.reddit.com/api/comment', data={'parent': parent_id, 'text': text}, headers={'Authorization': f'Bearer {access_token}', 'User-Agent': 'jarviscore/1.0'})
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f"Submit comment failed: {resp['status_code']} {resp['body']}"}
        data = resp['json']
        comments = data.get('jquery', [])
        comment_data = None
        for item in data.get('jquery', []):
            if isinstance(item, list) and len(item) > 3 and isinstance(item[3], list):
                for sub in item[3]:
                    if isinstance(sub, dict) and sub.get('kind') == 't1':
                        comment_data = sub.get('data')
                        break
        return {'success': True, 'data': comment_data or data, 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
