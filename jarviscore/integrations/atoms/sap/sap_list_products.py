async def sap_list_products(account_id: str, top: int=25, filter: str=None) -> list:
    """List products via the sap API."""
    _base = f'https://{account_id}.s4hana.ondemand.com'
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
    params = {'$top': top, '$format': 'json'}
    if filter:
        params['$filter'] = filter
    resp = await _get('/sap/opu/odata/sap/API_PRODUCT_SRV/A_Product', params=params, headers={'Accept': 'application/json'})
    results = resp.get('d', {}).get('results', [])
    return [{'id': p.get('Product'), 'type': p.get('ProductType'), 'description': p.get('ProductDescription'), 'base_unit': p.get('BaseUnit'), 'weight': p.get('GrossWeight'), 'weight_unit': p.get('WeightUnit'), 'created_at': p.get('CreationDate'), 'changed_at': p.get('LastChangeDate')} for p in results]
