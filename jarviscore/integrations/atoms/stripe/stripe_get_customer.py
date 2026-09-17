async def stripe_get_customer(customer_id: str) -> dict:
    """Get customer via the stripe API."""
    _h = {}
    resp = await nexus_call('GET', f'https://api.stripe.com/v1/customers/{customer_id}', headers=_h)
    if not resp['ok']:
        return {'success': False, 'error': resp['body']}
    data = resp['json']
    return {'success': True, 'id': data.get('id'), 'email': data.get('email'), 'name': data.get('name'), 'currency': data.get('currency'), 'balance': data.get('balance'), 'created': data.get('created')}
