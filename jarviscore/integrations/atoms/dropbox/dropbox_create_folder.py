async def dropbox_create_folder(dropbox_path: str, autorename: bool=False) -> dict:
    """Create folder. POST https://api.dropboxapi.com/2/files/create_folder_v2"""
    try:
        resp = await nexus_call('POST', 'https://api.dropboxapi.com/2/files/create_folder_v2', json={'path': dropbox_path, 'autorename': autorename}, headers={'Content-Type': 'application/json'})
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f"Create folder failed: {resp['status_code']} {resp['body']}"}
        return {'success': True, 'data': resp['json'].get('metadata'), 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
