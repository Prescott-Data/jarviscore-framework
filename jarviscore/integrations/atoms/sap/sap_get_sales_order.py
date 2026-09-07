async def sap_get_sales_order(account_id: str, order_id: str) -> dict:
    """Get sales order via the sap API."""
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
    resp = await _get(f"/sap/opu/odata/sap/API_SALES_ORDER_SRV/A_SalesOrder('{order_id}')", params={'$format': 'json', '$expand': 'to_Item'}, headers={'Accept': 'application/json'})
    o = resp.get('d', {})
    items_raw = o.get('to_Item', {}).get('results', [])
    return {'id': o.get('SalesOrder'), 'type': o.get('SalesOrderType'), 'customer': o.get('SoldToParty'), 'ship_to': o.get('ShipToParty'), 'currency': o.get('TransactionCurrency'), 'net_amount': o.get('TotalNetAmount'), 'date': o.get('SalesOrderDate'), 'delivery_date': o.get('RequestedDeliveryDate'), 'status': o.get('OverallSDProcessStatus'), 'items': [{'item_number': i.get('SalesOrderItem'), 'material': i.get('Material'), 'description': i.get('SalesOrderItemText'), 'quantity': i.get('RequestedQuantity'), 'unit': i.get('RequestedQuantityUnit'), 'net_amount': i.get('NetAmount')} for i in items_raw]}
