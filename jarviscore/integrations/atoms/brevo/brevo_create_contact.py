async def brevo_create_contact(email: str, first_name: str='', last_name: str='', list_ids: list=None) -> dict:
    """Create contact. POST https://api.brevo.com/v3/contacts"""
    _h = {'Content-Type': 'application/json'}
    payload = {'email': email, 'attributes': {}}
    if first_name:
        payload['attributes']['FIRSTNAME'] = first_name
    if last_name:
        payload['attributes']['LASTNAME'] = last_name
    if list_ids:
        payload['listIds'] = list_ids
    resp = await nexus_call('POST', 'https://api.brevo.com/v3/contacts', headers=_h, json=payload)
    if not resp['ok']:
        return {'success': False, 'error': resp['body']}
    data = resp['json']
    return {'success': True, 'id': data.get('id'), 'email': email}
