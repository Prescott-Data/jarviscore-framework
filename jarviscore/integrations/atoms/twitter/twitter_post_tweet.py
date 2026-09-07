async def twitter_post_tweet(text: str) -> dict:
    """Post tweet. POST https://api.twitter.com/2/tweets"""
    try:
        access_token = _get_nexus_token(None)
    except Exception as e:
        return {'success': False, 'data': None, 'error': f'Auth error: {str(e)}'}
    try:
        resp = await nexus_call('POST', 'https://api.twitter.com/2/tweets', json={'text': text}, headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'})
        if resp['status_code'] not in (200, 201):
            return {'success': False, 'data': None, 'error': f'Post tweet failed: {resp['status_code']} {resp['body']}'}
        return {'success': True, 'data': resp['json'].get('data'), 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
