async def dropbox_upload_file(file_path: str, dropbox_path: str, overwrite: bool=True) -> dict:
    """Upload file. POST https://content.dropboxapi.com/2/files/upload"""
    import os
    try:
        access_token = _get_nexus_token(None)
    except Exception as e:
        return {'success': False, 'data': None, 'error': f'Auth error: {str(e)}'}
    try:
        mode = 'overwrite' if overwrite else 'add'
        with open(file_path, 'rb') as f:
            resp = await nexus_call('POST', 'https://content.dropboxapi.com/2/files/upload', headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/octet-stream', 'Dropbox-API-Arg': f'{{"path": "{dropbox_path}", "mode": "{mode}", "autorename": true}}'}, data=f)
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f"Upload failed: {resp['status_code']} {resp['body']}"}
        return {'success': True, 'data': resp['json'], 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
