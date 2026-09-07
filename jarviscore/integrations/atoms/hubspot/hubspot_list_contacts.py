async def hubspot_list_contacts(limit: int=50, after: str=None) -> dict:
    """List contacts. GET https://api.hubapi.com/crm/v3/objects/contacts"""
    _h = {}
    params = {'limit': limit, 'properties': 'email,firstname,lastname,company'}
    if after:
        params['after'] = after
    resp = await nexus_call('GET', 'https://api.hubapi.com/crm/v3/objects/contacts', headers=_h, params=params)
    if not resp['ok']:
        return {'success': False, 'error': resp['body']}
    data = resp['json']
    return {'success': True, 'contacts': data.get('results', []), 'paging': data.get('paging')}
