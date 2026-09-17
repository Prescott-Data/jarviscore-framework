async def apollo_search_organizations(q_organization_name: str=None, locations: list=None, industries: list=None, employee_count_min: int=None, employee_count_max: int=None, page: int=1) -> dict:
    """Search organizations. POST https://api.apollo.io/v1/mixed_companies/search"""
    _h = {'Content-Type': 'application/json'}
    payload = {'page': page, 'per_page': 25}
    if q_organization_name:
        payload['q_organization_name'] = q_organization_name
    if locations:
        payload['organization_locations'] = locations
    if industries:
        payload['organization_industry_tag_ids'] = industries
    if employee_count_min:
        payload['organization_num_employees_ranges'] = [f'{employee_count_min},{employee_count_max or 100000}']
    resp = await nexus_call('POST', 'https://api.apollo.io/v1/mixed_companies/search', headers=_h, json=payload)
    if not resp['ok']:
        return {'success': False, 'error': resp['body']}
    data = resp['json']
    return {'success': True, 'organizations': data.get('organizations', []), 'total_entries': data.get('pagination', {}).get('total_entries', 0)}
