async def zoho_books_get_invoices(org_id: str, status: str=None) -> dict:
    """Books get invoices. GET https://www.zohoapis.com/books/v3/invoices"""
    try:
        access_token = _get_nexus_token(None)
    except Exception as e:
        return {'success': False, 'data': None, 'error': f'Auth error: {str(e)}'}
    try:
        params = {'organization_id': org_id}
        if status:
            params['status'] = status
        resp = await nexus_call('GET', 'https://www.zohoapis.com/books/v3/invoices', headers={'Authorization': f'Zoho-oauthtoken {access_token}'}, params=params)
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f"Get invoices failed: {resp['status_code']} {resp['body']}"}
        data = resp['json']
        if data.get('code') != 0:
            return {'success': False, 'data': None, 'error': data.get('message')}
        invoices = data.get('invoices', [])
        return {'success': True, 'data': {'invoices': invoices, 'count': len(invoices)}, 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
