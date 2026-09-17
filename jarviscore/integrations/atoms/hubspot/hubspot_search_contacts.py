async def hubspot_search_contacts(query: str, limit: int=50, after: int=0) -> dict:
    """Search HubSpot contacts by the provider's searchable contact properties."""
    body = {
        'query': query,
        'limit': limit,
        'after': after,
        'properties': ['email', 'firstname', 'lastname', 'company'],
    }
    resp = await nexus_call(
        'POST',
        'https://api.hubapi.com/crm/v3/objects/contacts/search',
        provider='hubspot',
        json=body,
    )
    if not resp['ok']:
        return {'success': False, 'error': resp['body']}
    data = resp['json']
    return {
        'success': True,
        'contacts': data.get('results', []),
        'paging': data.get('paging'),
        'total': data.get('total'),
    }