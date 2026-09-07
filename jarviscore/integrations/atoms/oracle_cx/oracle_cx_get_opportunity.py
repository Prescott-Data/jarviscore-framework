async def oracle_cx_get_opportunity(instance_url: str, opportunity_id: str) -> dict:
    """Cx get opportunity via the oracle_cx API."""
    _base = f'{instance_url.rstrip('/')}/crmRestApi/resources/latest'
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
    resp = await _get(f'/opportunities/{opportunity_id}')
    return {'id': resp.get('OptyId'), 'name': resp.get('Name'), 'description': resp.get('Description'), 'status': resp.get('StatusCode'), 'sales_stage': resp.get('SalesStage'), 'win_probability': resp.get('WinProb'), 'revenue': resp.get('Revenue'), 'currency': resp.get('CurrencyCode'), 'close_date': resp.get('CloseDate'), 'owner': resp.get('OwnerName'), 'account': resp.get('TargetPartyName'), 'created_at': resp.get('CreationDate'), 'updated_at': resp.get('LastUpdateDate')}
