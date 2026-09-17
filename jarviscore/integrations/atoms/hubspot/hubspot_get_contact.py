async def hubspot_get_contact(contact_id: str) -> dict:
    """Get contact via the hubspot API."""
    _h = {}
    resp = await nexus_call('GET', f'https://api.hubapi.com/crm/v3/objects/contacts/{contact_id}', headers=_h, params={'properties': 'email,firstname,lastname,company,phone,hs_lead_status'})
    if not resp['ok']:
        return {'success': False, 'error': resp['body']}
    data = resp['json']
    return {'success': True, 'id': data.get('id'), 'properties': data.get('properties', {})}
