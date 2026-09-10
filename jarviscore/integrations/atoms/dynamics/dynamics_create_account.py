async def dynamics_create_account(org_url: str, name: str, email: str=None, phone: str=None, website: str=None) -> dict:
    """Create account via the dynamics API."""
    try:
        payload = {'name': name}
        if email:
            payload['emailaddress1'] = email
        if phone:
            payload['telephone1'] = phone
        if website:
            payload['websiteurl'] = website
        resp = await nexus_call('POST', f"{org_url.rstrip('/')}/api/data/v9.2/accounts", headers={'OData-MaxVersion': '4.0', 'OData-Version': '4.0', 'Accept': 'application/json', 'Content-Type': 'application/json', 'Prefer': 'return=representation'}, json=payload)
        if resp['status_code'] not in (200, 201):
            return {'success': False, 'data': None, 'error': f"Create account failed: {resp['status_code']} {resp['body']}"}
        return {'success': True, 'data': resp['json'], 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
