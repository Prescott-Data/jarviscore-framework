async def reddit_get_subreddit(subreddit: str, limit: int=10) -> dict:
    """Get subreddit via the reddit API."""
    try:
        access_token = _get_nexus_token(None)
    except Exception as e:
        return {'success': False, 'data': None, 'error': f'Auth error: {str(e)}'}
    try:
        headers = {'Authorization': f'Bearer {access_token}', 'User-Agent': 'jarviscore/1.0'}
        about_resp = await nexus_call('GET', f'https://oauth.reddit.com/r/{subreddit}/about', headers=headers)
        if about_resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f'Get subreddit failed: {about_resp['status_code']} {about_resp['body']}'}
        posts_resp = await nexus_call('GET', f'https://oauth.reddit.com/r/{subreddit}/hot', params={'limit': limit}, headers=headers)
        posts = []
        if posts_resp['status_code'] == 200:
            posts = [p['data'] for p in posts_resp['json'].get('data', {}).get('children', [])]
        about = about_resp['json'].get('data', {})
        return {'success': True, 'data': {'name': about.get('display_name'), 'title': about.get('title'), 'description': about.get('public_description'), 'subscribers': about.get('subscribers'), 'hot_posts': posts}, 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
