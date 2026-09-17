async def apollo_search_people(job_titles: list=None, locations: list=None, organization_domains: list=None, page: int=1, per_page: int=25) -> dict:
    """Search people. POST https://api.apollo.io/v1/mixed_people/search"""
    _h = {'Content-Type': 'application/json', 'Cache-Control': 'no-cache'}
    payload = {'page': page, 'per_page': per_page}
    if job_titles:
        payload['person_titles'] = job_titles
    if locations:
        payload['person_locations'] = locations
    if organization_domains:
        payload['organization_domains'] = organization_domains
    resp = await nexus_call('POST', 'https://api.apollo.io/v1/mixed_people/search', headers=_h, json=payload)
    if not resp['ok']:
        return {'success': False, 'error': resp['body']}
    data = resp['json']
    return {'success': True, 'people': data.get('people', []), 'total_entries': data.get('pagination', {}).get('total_entries', 0), 'page': page}
