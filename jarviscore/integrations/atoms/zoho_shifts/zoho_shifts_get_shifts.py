async def zoho_shifts_get_shifts(org_id: str, start_date: str, end_date: str) -> dict:
    """Shifts get shifts via the zoho_shifts API."""
    try:
        access_token = _get_nexus_token(None)
    except Exception as e:
        return {'success': False, 'data': None, 'error': f'Auth error: {str(e)}'}
    try:
        resp = await nexus_call('GET', f'https://shifts.zoho.com/api/v1/{org_id}/shifts', headers={'Authorization': f'Zoho-oauthtoken {access_token}'}, params={'start_date': start_date, 'end_date': end_date})
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f'Get shifts failed: {resp['status_code']} {resp['body']}'}
        shifts = resp['json'].get('shifts', [])
        return {'success': True, 'data': {'shifts': shifts, 'count': len(shifts)}, 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
