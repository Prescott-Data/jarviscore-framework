async def apollo_search_organizations(q_organization_name: str=None, locations: list=None, keyword_tags: list=None, employee_count_min: int=None, employee_count_max: int=None, page: int=1, per_page: int=25) -> dict:
    """Find companies in Apollo by name, headquarters location, industry keywords and headcount. Consumes one Apollo credit per page."""
    params = {'page': page, 'per_page': per_page}
    if q_organization_name:
        params['q_organization_name'] = q_organization_name
    if locations:
        params['organization_locations[]'] = locations
    if keyword_tags:
        params['q_organization_keyword_tags[]'] = keyword_tags
    if employee_count_min or employee_count_max:
        params['organization_num_employees_ranges[]'] = [
            f'{employee_count_min or 1},{employee_count_max or 1000000}'
        ]
    resp = await nexus_call(
        'POST',
        'https://api.apollo.io/api/v1/mixed_companies/search',
        provider='apollo',
        params=params,
    )
    if not resp['ok']:
        return {'success': False, 'error': resp['body']}
    data = resp['json']
    return {
        'success': True,
        'organizations': data.get('organizations', []),
        'total_entries': (data.get('pagination') or {}).get('total_entries', 0),
        'page': page,
    }
