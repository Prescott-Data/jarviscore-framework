async def linkedin_get_organization(organization_id: str) -> dict:
    """Get organization via the linkedin API."""
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
    o = await _get(f'/organizations/{organization_id}', params={'projection': '(id,name,vanityName,description,staffCountRange,industries,logoV2)'})
    name = o.get('name', {}).get('localized', {})
    desc = o.get('description', {}).get('localized', {})
    return {'id': o.get('id'), 'name': next(iter(name.values()), None) if name else None, 'vanity_name': o.get('vanityName'), 'description': next(iter(desc.values()), None) if desc else None, 'staff_count_range': o.get('staffCountRange'), 'industries': o.get('industries', []), 'profile_url': f"https://www.linkedin.com/company/{o.get('vanityName')}" if o.get('vanityName') else None}
