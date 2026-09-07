async def youtube_get_channel(channel_id: str) -> dict:
    """Get channel via the youtube API."""
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
    resp = await _get('/channels', params={'part': 'snippet,statistics,contentDetails', 'id': channel_id})
    items = resp.get('items', [])
    if not items:
        raise ValueError(f"Channel '{channel_id}' not found")
    item = items[0]
    return {'id': item['id'], 'title': item['snippet']['title'], 'description': item['snippet']['description'], 'published_at': item['snippet']['publishedAt'], 'subscriber_count': item['statistics'].get('subscriberCount'), 'video_count': item['statistics'].get('videoCount'), 'view_count': item['statistics'].get('viewCount'), 'thumbnail': item['snippet']['thumbnails'].get('default', {}).get('url'), 'uploads_playlist_id': item['contentDetails']['relatedPlaylists'].get('uploads')}
