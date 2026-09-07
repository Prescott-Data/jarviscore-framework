async def youtube_get_video(video_id: str) -> dict:
    """Get video via the youtube API."""
    _base = 'https://www.googleapis.com/youtube/v3'
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
    resp = await _get('/videos', params={'part': 'snippet,contentDetails,statistics', 'id': video_id})
    items = resp.get('items', [])
    if not items:
        raise ValueError(f"Video '{video_id}' not found")
    item = items[0]
    return {'id': item['id'], 'title': item['snippet']['title'], 'description': item['snippet']['description'], 'channel': item['snippet']['channelTitle'], 'published_at': item['snippet']['publishedAt'], 'duration': item['contentDetails']['duration'], 'view_count': item['statistics'].get('viewCount'), 'like_count': item['statistics'].get('likeCount'), 'comment_count': item['statistics'].get('commentCount'), 'thumbnail': item['snippet']['thumbnails'].get('high', {}).get('url')}
