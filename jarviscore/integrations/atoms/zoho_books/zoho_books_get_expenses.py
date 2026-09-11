async def zoho_books_get_expenses(org_id: str, status: str=None) -> dict:
    """Books get expenses. GET https://www.zohoapis.com/books/v3/expenses"""
    try:
        params = {'organization_id': org_id}
        if status:
            params['filter_by'] = f'Status.{status.capitalize()}'
        resp = await nexus_call('GET', 'https://www.zohoapis.com/books/v3/expenses', params=params)
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f"Get expenses failed: {resp['status_code']} {resp['body']}"}
        data = resp['json']
        if data.get('code') != 0:
            return {'success': False, 'data': None, 'error': data.get('message')}
        expenses = data.get('expenses', [])
        return {'success': True, 'data': {'expenses': expenses, 'count': len(expenses)}, 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
