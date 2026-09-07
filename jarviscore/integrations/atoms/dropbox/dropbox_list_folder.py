async def dropbox_list_folder(dropbox_path: str='', recursive: bool=False) -> dict:
    """List folder. POST https://api.dropboxapi.com/2/files/list_folder"""
    try:
        access_token = _get_nexus_token(None)
    except Exception as e:
        return {'success': False, 'data': None, 'error': f'Auth error: {str(e)}'}
    try:
        resp = await nexus_call('POST', 'https://api.dropboxapi.com/2/files/list_folder', json={'path': dropbox_path, 'recursive': recursive}, headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'})
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f'List folder failed: {resp['status_code']} {resp['body']}'}
        result = resp['json']
        entries = result.get('entries', [])
        while result.get('has_more'):
            cursor_resp = await nexus_call('POST', 'https://api.dropboxapi.com/2/files/list_folder/continue', json={'cursor': result['cursor']}, headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'})
            if cursor_resp['status_code'] != 200:
                break
            result = cursor_resp['json']
            entries.extend(result.get('entries', []))
        return {'success': True, 'data': {'entries': entries, 'count': len(entries)}, 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
