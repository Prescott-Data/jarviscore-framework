async def brevo_get_contacts(limit: int=50, offset: int=0) -> dict:
    """Get contacts. GET https://api.brevo.com/v3/contacts"""
    _h = {}
    resp = await nexus_call('GET', 'https://api.brevo.com/v3/contacts', headers=_h, params={'limit': limit, 'offset': offset})
    if not resp['ok']:
        return {'success': False, 'error': resp['body']}
    data = resp['json']
    return {'success': True, 'contacts': data.get('contacts', []), 'count': data.get('count', 0)}
