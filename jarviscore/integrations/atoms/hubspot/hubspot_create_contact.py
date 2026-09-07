async def hubspot_create_contact(email: str, first_name: str='', last_name: str='', company: str='', phone: str='') -> dict:
    """Create contact. POST https://api.hubapi.com/crm/v3/objects/contacts"""
    _h = {'Content-Type': 'application/json'}
    props = {'email': email}
    if first_name:
        props['firstname'] = first_name
    if last_name:
        props['lastname'] = last_name
    if company:
        props['company'] = company
    if phone:
        props['phone'] = phone
    resp = await nexus_call('POST', 'https://api.hubapi.com/crm/v3/objects/contacts', headers=_h, json={'properties': props})
    if not resp['ok']:
        return {'success': False, 'error': resp['body']}
    data = resp['json']
    return {'success': True, 'id': data.get('id'), 'email': email, 'created_at': data.get('createdAt')}
