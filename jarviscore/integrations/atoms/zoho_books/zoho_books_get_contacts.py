async def zoho_books_get_contacts(org_id: str, contact_type: str=None) -> dict:
    """Books get contacts. GET https://www.zohoapis.com/books/v3/contacts"""
    try:
        params = {'organization_id': org_id}
        if contact_type:
            params['contact_type'] = contact_type
        resp = await nexus_call('GET', 'https://www.zohoapis.com/books/v3/contacts', params=params)
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f"Get contacts failed: {resp['status_code']} {resp['body']}"}
        data = resp['json']
        if data.get('code') != 0:
            return {'success': False, 'data': None, 'error': data.get('message')}
        contacts = data.get('contacts', [])
        return {'success': True, 'data': {'contacts': contacts, 'count': len(contacts)}, 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
