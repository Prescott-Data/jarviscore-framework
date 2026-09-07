async def openmrs_get_patient(patient_uuid: str) -> dict:
    """Get patient via the openmrs API."""
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
    p = await _get(f'/patient/{patient_uuid}', params={'v': 'full'})
    person = p.get('person', {})
    names = person.get('names', [])
    preferred_name = next((n for n in names if n.get('preferred')), names[0] if names else {})
    return {'uuid': p.get('uuid'), 'given_name': preferred_name.get('givenName'), 'family_name': preferred_name.get('familyName'), 'gender': person.get('gender'), 'age': person.get('age'), 'birthdate': person.get('birthdate'), 'dead': person.get('dead', False), 'death_date': person.get('deathDate'), 'identifiers': [{'id': i.get('identifier'), 'type': i.get('identifierType', {}).get('display'), 'preferred': i.get('preferred')} for i in p.get('identifiers', [])], 'addresses': [{'address1': a.get('address1'), 'city': a.get('cityVillage'), 'country': a.get('country')} for a in person.get('addresses', [])]}
