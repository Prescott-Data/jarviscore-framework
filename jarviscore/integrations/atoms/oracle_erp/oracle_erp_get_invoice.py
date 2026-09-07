async def oracle_erp_get_invoice(instance_url: str, invoice_id: str) -> dict:
    """Erp get invoice via the oracle_erp API."""
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
    resp = await _get(f'/invoices/{invoice_id}')
    return {'id': resp.get('InvoiceId'), 'number': resp.get('InvoiceNumber'), 'type': resp.get('InvoiceType'), 'supplier': resp.get('Supplier'), 'supplier_site': resp.get('SupplierSite'), 'amount': resp.get('InvoiceAmount'), 'currency': resp.get('InvoiceCurrencyCode'), 'date': resp.get('InvoiceDate'), 'due_date': resp.get('PaymentDueDate'), 'status': resp.get('InvoiceStatus'), 'payment_method': resp.get('PaymentMethod'), 'description': resp.get('Description'), 'created_by': resp.get('CreatedBy'), 'created_at': resp.get('CreationDate')}
