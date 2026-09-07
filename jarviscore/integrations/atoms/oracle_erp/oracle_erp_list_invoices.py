async def oracle_erp_list_invoices(instance_url: str, limit: int=25, offset: int=0) -> list:
    """Erp list invoices via the oracle_erp API."""
    _base = f"{instance_url.rstrip('/')}/fscmRestApi/resources/latest"
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
    resp = await _get('/invoices', params={'limit': limit, 'offset': offset})
    return [{'id': i.get('InvoiceId'), 'number': i.get('InvoiceNumber'), 'type': i.get('InvoiceType'), 'supplier': i.get('Supplier'), 'amount': i.get('InvoiceAmount'), 'currency': i.get('InvoiceCurrencyCode'), 'date': i.get('InvoiceDate'), 'due_date': i.get('PaymentDueDate'), 'status': i.get('InvoiceStatus'), 'description': i.get('Description')} for i in resp.get('items', [])]
