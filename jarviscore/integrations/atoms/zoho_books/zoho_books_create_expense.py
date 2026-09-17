async def zoho_books_create_expense(org_id: str, account_id: str, amount: float, date: str, paid_through_account_id: str, description: str=None, customer_id: str=None) -> dict:
    """Books create expense. POST https://www.zohoapis.com/books/v3/expenses"""
    try:
        payload = {'account_id': account_id, 'amount': amount, 'date': date, 'paid_through_account_id': paid_through_account_id}
        if description:
            payload['description'] = description
        if customer_id:
            payload['customer_id'] = customer_id
        resp = await nexus_call('POST', 'https://www.zohoapis.com/books/v3/expenses', headers={'Content-Type': 'application/json'}, params={'organization_id': org_id}, json=payload)
        if resp['status_code'] not in (200, 201):
            return {'success': False, 'data': None, 'error': f"Create expense failed: {resp['status_code']} {resp['body']}"}
        data = resp['json']
        if data.get('code') != 0:
            return {'success': False, 'data': None, 'error': data.get('message')}
        return {'success': True, 'data': data.get('expense'), 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
