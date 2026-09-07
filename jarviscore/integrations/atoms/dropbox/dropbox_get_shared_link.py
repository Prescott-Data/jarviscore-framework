async def dropbox_get_shared_link(dropbox_path: str) -> dict:
    """Get shared link. POST https://api.dropboxapi.com/2/sharing/create_shared_link_with_settings"""
    try:
        access_token = _get_nexus_token(None)
    except Exception as e:
        return {'success': False, 'data': None, 'error': f'Auth error: {str(e)}'}
    try:
        resp = await nexus_call('POST', 'https://api.dropboxapi.com/2/sharing/create_shared_link_with_settings', json={'path': dropbox_path, 'settings': {'requested_visibility': 'public'}}, headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'})
        if resp['status_code'] == 409 and 'shared_link_already_exists' in resp['body']:
            existing_resp = await nexus_call('POST', 'https://api.dropboxapi.com/2/sharing/list_shared_links', json={'path': dropbox_path, 'direct_only': True}, headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'})
            if existing_resp['status_code'] != 200:
                return {'success': False, 'data': None, 'error': f"Fetch existing link failed: {existing_resp['status_code']} {existing_resp['body']}"}
            links = existing_resp['json'].get('links', [])
            return {'success': True, 'data': links[0] if links else None, 'error': None}
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f"Create shared link failed: {resp['status_code']} {resp['body']}"}
        return {'success': True, 'data': resp['json'], 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
