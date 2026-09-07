async def oracle_erp_list_purchase_orders(instance_url: str, limit: int=25, offset: int=0) -> list:
    """Erp list purchase orders via the oracle_erp API."""
    _base = f'{instance_url.rstrip('/')}/fscmRestApi/resources/latest'
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
    resp = await _get('/purchaseOrders', params={'limit': limit, 'offset': offset})
    return [{'id': o.get('POHeaderId'), 'number': o.get('OrderNumber'), 'supplier': o.get('Supplier'), 'status': o.get('DocumentStatus'), 'currency': o.get('Currency'), 'amount': o.get('Amount'), 'ordered_date': o.get('OrderedDate'), 'buyer': o.get('BuyerName'), 'description': o.get('Description')} for o in resp.get('items', [])]
