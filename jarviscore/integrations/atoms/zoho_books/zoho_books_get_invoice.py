async def zoho_books_get_invoice(org_id: str, invoice_id: str) -> dict:
    """Books get invoice via the zoho_books API."""
    try:
        access_token = _get_nexus_token(None)
    except Exception as e:
        return {'success': False, 'data': None, 'error': f'Auth error: {str(e)}'}
    try:
        resp = await nexus_call('GET', f'https://www.zohoapis.com/books/v3/invoices/{invoice_id}', headers={'Authorization': f'Zoho-oauthtoken {access_token}'}, params={'organization_id': org_id})
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f"Get invoice failed: {resp['status_code']} {resp['body']}"}
        data = resp['json']
        if data.get('code') != 0:
            return {'success': False, 'data': None, 'error': data.get('message')}
        return {'success': True, 'data': data.get('invoice'), 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
