async def google_drive_share_file(file_id: str, email: str, role: str='reader') -> dict:
    """Drive share file via the google_drive API."""
    scopes = ['https://www.googleapis.com/auth/drive']
    try:
        access_token = _get_nexus_token(None, scopes)
    except Exception as e:
        return {'success': False, 'file_id': file_id, 'data': None, 'error': f'Nexus token error: {str(e)}'}
    try:
        permission = {'type': 'user', 'role': role, 'emailAddress': email}
        resp = await nexus_call('POST', f'https://www.googleapis.com/drive/v3/files/{file_id}/permissions', json=permission, headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'})
        if resp['status_code'] not in (200, 201):
            return {'success': False, 'file_id': file_id, 'data': None, 'error': f'Share failed: {resp['status_code']} {resp['body']}'}
        return {'success': True, 'file_id': file_id, 'data': resp['json'], 'error': None}
    except Exception as e:
        return {'success': False, 'file_id': file_id, 'data': None, 'error': str(e)}
