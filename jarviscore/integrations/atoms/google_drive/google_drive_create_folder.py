ATOM_POLICY = {
    "effect": "write",
    "approval": "never",
    "idempotency_fields": ["parent_folder_id", "folder_name"],
    "consequence": "Creates one Google Drive folder.",
}


async def google_drive_create_folder(folder_name: str, parent_folder_id: str=None) -> dict:
    """Drive create folder. POST https://www.googleapis.com/drive/v3/files"""
    try:
        metadata = {'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder'}
        if parent_folder_id:
            metadata['parents'] = [parent_folder_id]
        resp = await nexus_call(
            'POST',
            'https://www.googleapis.com/drive/v3/files',
            provider='google_drive',
            params={'fields': 'id,name,webViewLink,parents'},
            json=metadata,
        )
        if not resp['ok']:
            return {'success': False, 'data': None, 'error': resp['body']}
        return {'success': True, 'data': resp['json'], 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
