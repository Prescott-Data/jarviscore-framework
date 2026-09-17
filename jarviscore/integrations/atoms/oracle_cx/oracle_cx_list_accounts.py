async def oracle_cx_list_accounts(instance_url: str, limit: int=25, offset: int=0) -> list:
    """Cx list accounts via the oracle_cx API."""
    _base = f"{instance_url.rstrip('/')}/crmRestApi/resources/latest"
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
    resp = await _get('/accounts', params={'limit': limit, 'offset': offset})
    return [{'id': a.get('PartyId'), 'name': a.get('OrganizationName'), 'type': a.get('Type'), 'status': a.get('AccountStatus'), 'industry': a.get('IndustryCode'), 'revenue': a.get('AnnualRevenue'), 'currency': a.get('CurrencyCode'), 'employees': a.get('NumberOfEmployees'), 'owner': a.get('OwnerName'), 'created_at': a.get('CreationDate')} for a in resp.get('items', [])]
