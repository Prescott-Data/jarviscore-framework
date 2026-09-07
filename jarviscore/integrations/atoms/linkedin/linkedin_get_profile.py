async def linkedin_get_profile() -> dict:
    """Get profile via the linkedin API."""
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
    p = await _get('/me', params={'projection': '(id,firstName,lastName,headline,vanityName,profilePicture(displayImage~:playableStreams))'})
    first = p.get('firstName', {}).get('localized', {})
    last = p.get('lastName', {}).get('localized', {})
    first_name = next(iter(first.values()), None) if first else None
    last_name = next(iter(last.values()), None) if last else None
    return {'id': p.get('id'), 'first_name': first_name, 'last_name': last_name, 'headline': next(iter(p.get('headline', {}).get('localized', {}).values()), None), 'vanity_name': p.get('vanityName'), 'profile_url': f'https://www.linkedin.com/in/{p.get('vanityName')}' if p.get('vanityName') else None}
