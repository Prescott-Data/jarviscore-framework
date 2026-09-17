async def _get_twitter_user_id() -> str:
    resp = await nexus_call('GET', 'https://api.twitter.com/2/users/me')
    if not resp['ok']:
        raise RuntimeError(resp['body'])
    return resp['json']['data']['id']

async def twitter_like_tweet(tweet_id: str) -> dict:
    """Like tweet via the twitter API."""
    try:
        twitter_user_id = await _get_twitter_user_id()
    except Exception as e:
        return {'success': False, 'data': None, 'error': f'Auth error: {str(e)}'}
    try:
        resp = await nexus_call('POST', f'https://api.twitter.com/2/users/{twitter_user_id}/likes', json={'tweet_id': tweet_id}, headers={'Content-Type': 'application/json'})
        if resp['status_code'] not in (200, 201):
            return {'success': False, 'data': None, 'error': f"Like tweet failed: {resp['status_code']} {resp['body']}"}
        return {'success': True, 'data': resp['json'].get('data'), 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
