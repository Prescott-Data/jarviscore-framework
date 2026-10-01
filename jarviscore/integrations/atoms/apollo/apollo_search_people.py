async def apollo_search_people(job_titles: list=None, seniorities: list=None, organization_domains: list=None, organization_ids: list=None, person_locations: list=None, organization_locations: list=None, keywords: str=None, page: int=1, per_page: int=25) -> dict:
    """Find prospects in Apollo by role, seniority, employer and location. Returns Apollo person IDs, first names and titles but no emails; enrich a person with apollo_get_person for email and LinkedIn URL."""
    params = {'page': page, 'per_page': per_page}
    if job_titles:
        params['person_titles[]'] = job_titles
    if seniorities:
        params['person_seniorities[]'] = seniorities
    if organization_domains:
        params['q_organization_domains_list[]'] = organization_domains
    if organization_ids:
        params['organization_ids[]'] = organization_ids
    if person_locations:
        params['person_locations[]'] = person_locations
    if organization_locations:
        params['organization_locations[]'] = organization_locations
    if keywords:
        params['q_keywords'] = keywords
    resp = await nexus_call(
        'POST',
        'https://api.apollo.io/api/v1/mixed_people/api_search',
        provider='apollo',
        params=params,
    )
    if not resp['ok']:
        return {'success': False, 'error': resp['body']}
    data = resp['json']
    return {
        'success': True,
        'people': data.get('people', []),
        'total_entries': data.get('total_entries', 0),
        'page': page,
    }
