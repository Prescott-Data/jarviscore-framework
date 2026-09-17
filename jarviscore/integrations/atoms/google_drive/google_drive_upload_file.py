ATOM_POLICY = {
    "effect": "write",
    "approval": "never",
    "idempotency_fields": ["folder_id", "file_name", "file_path"],
    "consequence": "Uploads one file to Google Drive.",
}


async def google_drive_upload_file(file_path: str, folder_id: str=None, file_name: str=None) -> dict:
    """Drive upload file. POST https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart"""
    import json
    import os
    try:
        name = file_name or os.path.basename(file_path)
        metadata = {'name': name}
        if folder_id:
            metadata['parents'] = [folder_id]
        with open(file_path, 'rb') as f:
            file_content = f.read()
        import mimetypes
        mime_type = mimetypes.guess_type(file_path)[0] or 'application/octet-stream'
        boundary = 'boundary_gdrive_upload'
        body = (
            f'--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n'
            f'{json.dumps(metadata)}\r\n--{boundary}\r\nContent-Type: {mime_type}\r\n\r\n'
        ).encode() + file_content + f'\r\n--{boundary}--'.encode()
        resp = await nexus_call(
            'POST',
            'https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart',
            provider='google_drive',
            headers={'Content-Type': f'multipart/related; boundary={boundary}'},
            data=body,
        )
        if not resp['ok']:
            return {'success': False, 'data': None, 'error': resp['body']}
        return {'success': True, 'data': resp['json'], 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
