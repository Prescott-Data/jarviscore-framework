async def hubspot_list_contact_deals(contact_id: str, limit: int=100, after: str=None) -> dict:
    """List HubSpot deals associated with one contact."""
    params = {'limit': limit}
    if after:
        params['after'] = after
    resp = await nexus_call(
        'GET',
        f'https://api.hubapi.com/crm/v4/objects/contacts/{contact_id}/associations/deals',
        params=params,
        provider='hubspot',
    )
    if not resp['ok']:
        return {'success': False, 'contact_id': contact_id, 'deals': [], 'error': resp['body']}
    data = resp['json']
    return {
        'success': True,
        'contact_id': contact_id,
        'deals': data.get('results', []),
        'paging': data.get('paging'),
        'error': None,
    }