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

async def freshbooks_get_expense(expense_id: str) -> dict:
    """Get expense via the freshbooks API."""
    try:
        access_token = _get_nexus_token(None)
        account_id = await _get_account_id(access_token)
    except Exception as e:
        return {'success': False, 'expense_id': expense_id, 'data': None, 'error': f'Auth error: {str(e)}'}
    try:
        resp = await nexus_call('GET', f'https://api.freshbooks.com/accounting/account/{account_id}/expenses/expenses/{expense_id}', headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'})
        if resp['status_code'] != 200:
            return {'success': False, 'expense_id': expense_id, 'data': None, 'error': f"Get expense failed: {resp['status_code']} {resp['body']}"}
        return {'success': True, 'expense_id': expense_id, 'data': resp['json'].get('response', {}).get('result', {}).get('expense'), 'error': None}
    except Exception as e:
        return {'success': False, 'expense_id': expense_id, 'data': None, 'error': str(e)}
