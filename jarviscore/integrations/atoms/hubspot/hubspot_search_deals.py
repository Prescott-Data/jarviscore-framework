async def hubspot_search_deals(query: str, limit: int=50, after: int=0) -> dict:
    """Search HubSpot deals by provider-searchable deal properties."""
    body = {
        'query': query,
        'limit': limit,
        'after': after,
        'properties': ['dealname', 'dealstage', 'pipeline', 'amount', 'closedate'],
    }
    resp = await nexus_call(
        'POST',
        'https://api.hubapi.com/crm/v3/objects/deals/search',
        provider='hubspot',
        json=body,
    )
    if not resp['ok']:
        return {'success': False, 'deals': [], 'error': resp['body']}
    data = resp['json']
    return {
        'success': True,
        'deals': data.get('results', []),
        'paging': data.get('paging'),
        'total': data.get('total'),
        'error': None,
    }