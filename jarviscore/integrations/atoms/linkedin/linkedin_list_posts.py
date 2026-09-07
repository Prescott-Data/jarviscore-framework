async def linkedin_list_posts(author_urn: str, count: int=25, start: int=0) -> list:
    """List posts via the linkedin API."""
    _base = 'https://api.linkedin.com/v2'
    _h = {'Content-Type': 'application/json'}

    async def _get(p, params=None, headers=None):
        _r = await nexus_call('GET', f'{_base}{p}', headers={**_h, **(headers or {})}, params=params or {})
        if not _r['ok']:
            return {'success': False, 'error': _r['body']}
        return _r['json']

    async def _post(p, data=None, headers=None):
        _r = await nexus_call('POST', f'{_base}{p}', headers={**_h, **(headers or {})}, json=data)
        if not _r['ok']:
            return {'success': False, 'error': _r['body']}
        return _r['json']

    async def _put(p, data=None, headers=None):
        _r = await nexus_call('PUT', f'{_base}{p}', headers={**_h, **(headers or {})}, json=data)
        if not _r['ok']:
            return {'success': False, 'error': _r['body']}
        return _r['json']

    async def _patch(p, data=None, headers=None):
        _r = await nexus_call('PATCH', f'{_base}{p}', headers={**_h, **(headers or {})}, json=data)
        if not _r['ok']:
            return {'success': False, 'error': _r['body']}
        return _r['json'] if _r['content'] else {}

    async def _delete(p, headers=None):
        _r = await nexus_call('DELETE', f'{_base}{p}', headers={**_h, **(headers or {})})
        if not _r['ok']:
            return {'success': False, 'error': _r['body']}
        return _r['json'] if _r['content'] else {}
    resp = await _get('/ugcPosts', params={'q': 'authors', 'authors': f'List({author_urn})', 'count': count, 'start': start})
    return [{'id': post.get('id'), 'author': post.get('author'), 'created_at': post.get('created', {}).get('time'), 'visibility': post.get('visibility', {}).get('com.linkedin.ugc.MemberNetworkVisibility'), 'text': post.get('specificContent', {}).get('com.linkedin.ugc.ShareContent', {}).get('shareCommentary', {}).get('text'), 'media': [{'type': m.get('media'), 'status': m.get('status')} for m in post.get('specificContent', {}).get('com.linkedin.ugc.ShareContent', {}).get('media', [])]} for post in resp.get('elements', [])]
