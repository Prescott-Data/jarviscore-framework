async def zoho_shifts_update_shift(org_id: str, shift_id: str, start_time: str=None, end_time: str=None, employee_id: str=None, notes: str=None) -> dict:
    """Shifts update shift via the zoho_shifts API."""
    try:
        access_token = _get_nexus_token(None)
    except Exception as e:
        return {'success': False, 'data': None, 'error': f'Auth error: {str(e)}'}
    try:
        payload = {}
        if start_time:
            payload['start_time'] = start_time
        if end_time:
            payload['end_time'] = end_time
        if employee_id:
            payload['employee_id'] = employee_id
        if notes is not None:
            payload['notes'] = notes
        resp = await nexus_call('PUT', f'https://shifts.zoho.com/api/v1/{org_id}/shifts/{shift_id}', headers={'Authorization': f'Zoho-oauthtoken {access_token}', 'Content-Type': 'application/json'}, json=payload)
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f'Update shift failed: {resp['status_code']} {resp['body']}'}
        return {'success': True, 'data': resp['json'], 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
