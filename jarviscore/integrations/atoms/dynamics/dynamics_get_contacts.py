async def dynamics_get_contacts(org_url: str, max_results: int=50) -> dict:
    """Get contacts via the dynamics API."""
    try:
        resp = await nexus_call('GET', f"{org_url.rstrip('/')}/api/data/v9.2/contacts", headers={'OData-MaxVersion': '4.0', 'OData-Version': '4.0', 'Accept': 'application/json'}, params={'$top': max_results, '$select': 'contactid,fullname,emailaddress1,telephone1,jobtitle'})
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f"Get contacts failed: {resp['status_code']} {resp['body']}"}
        contacts = resp['json'].get('value', [])
        return {'success': True, 'data': {'contacts': contacts, 'count': len(contacts)}, 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
