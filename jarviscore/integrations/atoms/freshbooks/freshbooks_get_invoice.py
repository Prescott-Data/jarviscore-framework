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

async def freshbooks_get_invoice(invoice_id: str) -> dict:
    """Get invoice via the freshbooks API."""
    try:
        account_id = await _get_account_id()
    except Exception as e:
        return {'success': False, 'invoice_id': invoice_id, 'data': None, 'error': f'Auth error: {str(e)}'}
    try:
        resp = await nexus_call('GET', f'https://api.freshbooks.com/accounting/account/{account_id}/invoices/invoices/{invoice_id}', headers={'Content-Type': 'application/json'})
        if resp['status_code'] != 200:
            return {'success': False, 'invoice_id': invoice_id, 'data': None, 'error': f"Get invoice failed: {resp['status_code']} {resp['body']}"}
        return {'success': True, 'invoice_id': invoice_id, 'data': resp['json'].get('response', {}).get('result', {}).get('invoice'), 'error': None}
    except Exception as e:
        return {'success': False, 'invoice_id': invoice_id, 'data': None, 'error': str(e)}
