async def stripe_list_invoices(customer_id: str=None, status: str=None, limit: int=20) -> dict:
    """List invoices. GET https://api.stripe.com/v1/invoices"""
    _h = {}
    params = {'limit': limit}
    if customer_id:
        params['customer'] = customer_id
    if status:
        params['status'] = status
    resp = await nexus_call('GET', 'https://api.stripe.com/v1/invoices', headers=_h, params=params)
    if not resp['ok']:
        return {'success': False, 'error': resp['body']}
    data = resp['json']
    invoices = [{'id': inv['id'], 'customer': inv.get('customer'), 'amount_due': inv.get('amount_due'), 'currency': inv.get('currency'), 'status': inv.get('status'), 'due_date': inv.get('due_date')} for inv in data.get('data', [])]
    return {'success': True, 'invoices': invoices, 'has_more': data.get('has_more')}
