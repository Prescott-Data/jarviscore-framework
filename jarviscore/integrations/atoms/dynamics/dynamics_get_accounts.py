async def dynamics_get_accounts(org_url: str, max_results: int=50) -> dict:
    """Get accounts via the dynamics API."""
    try:
        access_token = _get_nexus_token(None)
    except Exception as e:
        return {'success': False, 'data': None, 'error': f'Auth error: {str(e)}'}
    try:
        resp = await nexus_call('GET', f"{org_url.rstrip('/')}/api/data/v9.2/accounts", headers={'Authorization': f'Bearer {access_token}', 'OData-MaxVersion': '4.0', 'OData-Version': '4.0', 'Accept': 'application/json'}, params={'$top': max_results, '$select': 'accountid,name,emailaddress1,telephone1,websiteurl'})
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f"Get accounts failed: {resp['status_code']} {resp['body']}"}
        accounts = resp['json'].get('value', [])
        return {'success': True, 'data': {'accounts': accounts, 'count': len(accounts)}, 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
