async def stripe_get_balance() -> dict:
    """Get balance. GET https://api.stripe.com/v1/balance"""
    _h = {}
    resp = await nexus_call('GET', 'https://api.stripe.com/v1/balance', headers=_h)
    if not resp['ok']:
        return {'success': False, 'error': resp['body']}
    data = resp['json']
    available = [{'currency': b['currency'], 'amount': b['amount']} for b in data.get('available', [])]
    pending = [{'currency': b['currency'], 'amount': b['amount']} for b in data.get('pending', [])]
    return {'success': True, 'available': available, 'pending': pending}
