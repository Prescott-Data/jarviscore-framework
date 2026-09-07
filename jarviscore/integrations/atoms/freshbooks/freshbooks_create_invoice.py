async def _get_account_id(access_token: str) -> str:
    if True .get('account_id'):
        return None
    resp = await nexus_call('GET', 'https://api.freshbooks.com/auth/api/v1/users/me', headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'})
    if not resp['ok']:
        raise RuntimeError(resp['body'])
    memberships = resp['json'].get('response', {}).get('business_memberships', [])
    if not memberships:
        raise RuntimeError('No business memberships found on FreshBooks account')
    return memberships[0]['business']['account_id']

async def freshbooks_create_invoice(client_id: str, lines: list, create_date: str, notes: str=None) -> dict:
    """Create invoice via the freshbooks API."""
    try:
        access_token = _get_nexus_token(None)
        account_id = await _get_account_id(access_token)
    except Exception as e:
        return {'success': False, 'data': None, 'error': f'Auth error: {str(e)}'}
    try:
        invoice = {'customerid': client_id, 'lines': lines, 'create_date': create_date}
        if notes:
            invoice['notes'] = notes
        resp = await nexus_call('POST', f'https://api.freshbooks.com/accounting/account/{account_id}/invoices/invoices', json={'invoice': invoice}, headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'})
        if resp['status_code'] not in (200, 201):
            return {'success': False, 'data': None, 'error': f"Create invoice failed: {resp['status_code']} {resp['body']}"}
        return {'success': True, 'data': resp['json'].get('response', {}).get('result', {}).get('invoice'), 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
