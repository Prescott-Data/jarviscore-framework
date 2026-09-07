async def google_drive_create_folder(folder_name: str, parent_folder_id: str=None) -> dict:
    """Drive create folder. POST https://www.googleapis.com/drive/v3/files"""
    scopes = ['https://www.googleapis.com/auth/drive']
    try:
        access_token = _get_nexus_token(None, scopes)
    except Exception as e:
        return {'success': False, 'data': None, 'error': f'Nexus token error: {str(e)}'}
    try:
        metadata = {'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder'}
        if parent_folder_id:
            metadata['parents'] = [parent_folder_id]
        resp = await nexus_call('POST', 'https://www.googleapis.com/drive/v3/files', json=metadata, headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'})
        if resp['status_code'] not in (200, 201):
            return {'success': False, 'data': None, 'error': f'Create folder failed: {resp['status_code']} {resp['body']}'}
        return {'success': True, 'data': resp['json'], 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
