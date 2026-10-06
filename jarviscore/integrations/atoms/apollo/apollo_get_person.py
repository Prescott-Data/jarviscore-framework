ATOM_POLICY = {
    "effect": "read",
    "approval": "never",
}


async def apollo_get_person(person_id: str=None, name: str=None, domain: str=None, linkedin_url: str=None) -> dict:
    """Enrich one person in Apollo by Apollo person ID, by full name plus employer domain, or by LinkedIn URL. Returns their work email, email status, LinkedIn URL and match confidence. Consumes Apollo credits when data is found."""
    params = {}
    if person_id:
        params['id'] = person_id
    if name:
        params['name'] = name
    if domain:
        params['domain'] = domain
    if linkedin_url:
        params['linkedin_url'] = linkedin_url
    if not params:
        return {'success': False, 'error': 'Provide person_id, name with domain, or linkedin_url.'}
    resp = await nexus_call(
        'POST',
        'https://api.apollo.io/api/v1/people/match',
        provider='apollo',
        params=params,
    )
    if not resp['ok']:
        return {'success': False, 'error': resp['body']}
    person = resp['json'].get('person') or {}
    organization = person.get('organization') or {}
    return {
        'success': True,
        'id': person.get('id'),
        'name': person.get('name'),
        'title': person.get('title'),
        'headline': person.get('headline'),
        'email': person.get('email'),
        'email_status': person.get('email_status'),
        'linkedin_url': person.get('linkedin_url'),
        'match_confidence': person.get('match_confidence'),
        'organization': organization.get('name'),
        'organization_domain': organization.get('primary_domain'),
    }
