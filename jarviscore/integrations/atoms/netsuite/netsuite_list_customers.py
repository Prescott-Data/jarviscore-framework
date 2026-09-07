async def netsuite_list_customers(account_id: str, limit: int=25, offset: int=0) -> list:
    """List customers via the netsuite API."""
    _base = f'https://{account_id}.suitetalk.api.netsuite.com/services/rest/record/v1'
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
    resp = await _get('/customer', params={'limit': limit, 'offset': offset})
    return [{'id': c.get('id'), 'name': c.get('companyName'), 'email': c.get('email'), 'phone': c.get('phone'), 'currency': c.get('currency', {}).get('refName') if isinstance(c.get('currency'), dict) else c.get('currency'), 'status': c.get('entityStatus', {}).get('refName') if isinstance(c.get('entityStatus'), dict) else c.get('entityStatus'), 'links': c.get('links', [])} for c in resp.get('items', [])]
