async def zoho_books_get_contact(org_id: str, contact_id: str) -> dict:
    """Books get contact via the zoho_books API."""
    try:
        resp = await nexus_call('GET', f'https://www.zohoapis.com/books/v3/contacts/{contact_id}', params={'organization_id': org_id})
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f"Get contact failed: {resp['status_code']} {resp['body']}"}
        data = resp['json']
        if data.get('code') != 0:
            return {'success': False, 'data': None, 'error': data.get('message')}
        return {'success': True, 'data': data.get('contact'), 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
