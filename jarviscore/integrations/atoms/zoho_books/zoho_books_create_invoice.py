async def zoho_books_create_invoice(org_id: str, customer_id: str, line_items: list, date: str=None, notes: str=None) -> dict:
    """Books create invoice. POST https://www.zohoapis.com/books/v3/invoices"""
    try:
        access_token = _get_nexus_token(None)
    except Exception as e:
        return {'success': False, 'data': None, 'error': f'Auth error: {str(e)}'}
    try:
        payload = {'customer_id': customer_id, 'line_items': line_items}
        if date:
            payload['date'] = date
        if notes:
            payload['notes'] = notes
        resp = await nexus_call('POST', 'https://www.zohoapis.com/books/v3/invoices', headers={'Authorization': f'Zoho-oauthtoken {access_token}', 'Content-Type': 'application/json'}, params={'organization_id': org_id}, json=payload)
        if resp['status_code'] not in (200, 201):
            return {'success': False, 'data': None, 'error': f"Create invoice failed: {resp['status_code']} {resp['body']}"}
        data = resp['json']
        if data.get('code') != 0:
            return {'success': False, 'data': None, 'error': data.get('message')}
        return {'success': True, 'data': data.get('invoice'), 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
