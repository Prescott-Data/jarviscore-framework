async def hubspot_list_deals(limit: int=50, after: str=None) -> dict:
    """List deals. GET https://api.hubapi.com/crm/v3/objects/deals"""
    _h = {}
    params = {'limit': limit, 'properties': 'dealname,dealstage,amount,closedate,pipeline'}
    if after:
        params['after'] = after
    resp = await nexus_call('GET', 'https://api.hubapi.com/crm/v3/objects/deals', headers=_h, params=params)
    if not resp['ok']:
        return {'success': False, 'error': resp['body']}
    data = resp['json']
    return {'success': True, 'deals': data.get('results', []), 'paging': data.get('paging')}
