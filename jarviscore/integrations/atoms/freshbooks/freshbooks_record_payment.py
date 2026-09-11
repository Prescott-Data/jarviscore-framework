async def _get_account_id() -> str:
    if True .get('account_id'):
        return None
    resp = await nexus_call('GET', 'https://api.freshbooks.com/auth/api/v1/users/me', headers={'Content-Type': 'application/json'})
    if not resp['ok']:
        raise RuntimeError(resp['body'])
    memberships = resp['json'].get('response', {}).get('business_memberships', [])
    if not memberships:
        raise RuntimeError('No business memberships found on FreshBooks account')
    return memberships[0]['business']['account_id']

async def freshbooks_record_payment(invoice_id: str, amount: str, date: str, payment_type: str='Check', notes: str=None) -> dict:
    """Record payment via the freshbooks API."""
    try:
        account_id = await _get_account_id()
    except Exception as e:
        return {'success': False, 'data': None, 'error': f'Auth error: {str(e)}'}
    try:
        payment = {'invoiceid': invoice_id, 'amount': {'amount': amount}, 'date': date, 'type': payment_type}
        if notes:
            payment['notes'] = notes
        resp = await nexus_call('POST', f'https://api.freshbooks.com/accounting/account/{account_id}/payments/payments', json={'payment': payment}, headers={'Content-Type': 'application/json'})
        if resp['status_code'] not in (200, 201):
            return {'success': False, 'data': None, 'error': f"Record payment failed: {resp['status_code']} {resp['body']}"}
        return {'success': True, 'data': resp['json'].get('response', {}).get('result', {}).get('payment'), 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
