async def reddit_vote(fullname: str, direction: int) -> dict:
    """Vote. POST https://oauth.reddit.com/api/vote"""
    try:
        resp = await nexus_call('POST', 'https://oauth.reddit.com/api/vote', data={'id': fullname, 'dir': direction}, headers={'User-Agent': 'jarviscore/1.0'})
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f"Vote failed: {resp['status_code']} {resp['body']}"}
        return {'success': True, 'data': {'fullname': fullname, 'direction': direction}, 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
