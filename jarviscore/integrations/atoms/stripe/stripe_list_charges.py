async def stripe_list_charges(customer_id: str=None, limit: int=20, created_gte: int=None) -> dict:
    """List charges. GET https://api.stripe.com/v1/charges"""
    _h = {}
    params = {'limit': limit}
    if customer_id:
        params['customer'] = customer_id
    if created_gte:
        params['created[gte]'] = created_gte
    resp = await nexus_call('GET', 'https://api.stripe.com/v1/charges', headers=_h, params=params)
    if not resp['ok']:
        return {'success': False, 'error': resp['body']}
    data = resp['json']
    charges = [{'id': c['id'], 'amount': c.get('amount'), 'currency': c.get('currency'), 'status': c.get('status'), 'customer': c.get('customer'), 'description': c.get('description'), 'created': c.get('created')} for c in data.get('data', [])]
    return {'success': True, 'charges': charges, 'has_more': data.get('has_more')}
