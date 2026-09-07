async def twitter_reply_tweet(text: str, reply_to_tweet_id: str) -> dict:
    """Reply tweet. POST https://api.twitter.com/2/tweets"""
    try:
        access_token = _get_nexus_token(None)
    except Exception as e:
        return {'success': False, 'data': None, 'error': f'Auth error: {str(e)}'}
    try:
        resp = await nexus_call('POST', 'https://api.twitter.com/2/tweets', json={'text': text, 'reply': {'in_reply_to_tweet_id': reply_to_tweet_id}}, headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'})
        if resp['status_code'] not in (200, 201):
            return {'success': False, 'data': None, 'error': f"Reply tweet failed: {resp['status_code']} {resp['body']}"}
        return {'success': True, 'data': resp['json'].get('data'), 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
