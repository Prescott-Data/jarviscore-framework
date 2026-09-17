async def openmrs_search_patients(query: str, limit: int=25) -> list:
    """Search patients via the openmrs API."""
    _base = 'https://o2.openmrs.org/openmrs/ws/rest/v1'
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
    resp = await _get('/patient', params={'q': query, 'limit': limit, 'v': 'default'})
    return [{'uuid': p.get('uuid'), 'display': p.get('display'), 'identifiers': [{'id': i.get('identifier'), 'type': i.get('identifierType', {}).get('display')} for i in p.get('identifiers', [])], 'gender': p.get('person', {}).get('gender'), 'age': p.get('person', {}).get('age'), 'birthdate': p.get('person', {}).get('birthdate'), 'dead': p.get('person', {}).get('dead', False)} for p in resp.get('results', [])]
