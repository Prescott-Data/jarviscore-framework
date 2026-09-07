async def openmrs_list_visits(patient_uuid: str, limit: int=25) -> list:
    """List visits via the openmrs API."""
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
    resp = await _get('/visit', params={'patient': patient_uuid, 'limit': limit, 'v': 'default'})
    return [{'uuid': v.get('uuid'), 'type': v.get('visitType', {}).get('display'), 'location': v.get('location', {}).get('display'), 'start_datetime': v.get('startDatetime'), 'stop_datetime': v.get('stopDatetime'), 'active': v.get('stopDatetime') is None} for v in resp.get('results', [])]
