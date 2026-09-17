async def google_drive_export_file(file_id: str, mime_type: str='text/plain') -> dict:
    """Export a Google Workspace file in a requested MIME type."""
    import base64

    resp = await nexus_call(
        'GET',
        f'https://www.googleapis.com/drive/v3/files/{file_id}/export',
        params={'mimeType': mime_type},
        provider='google_drive',
    )
    if not resp['ok']:
        return {'success': False, 'file_id': file_id, 'mime_type': mime_type, 'content': None, 'error': resp['body']}
    content = resp.get('content', b'')
    textual = mime_type.startswith('text/') or mime_type in {
        'application/json', 'application/xml', 'application/xhtml+xml'
    }
    if isinstance(content, bytes) and textual:
        content = content.decode('utf-8')
    if isinstance(content, bytes):
        return {
            'success': True,
            'file_id': file_id,
            'mime_type': mime_type,
            'content': None,
            'content_base64': base64.b64encode(content).decode('ascii'),
            'encoding': 'base64',
            'error': None,
        }
    return {
        'success': True,
        'file_id': file_id,
        'mime_type': mime_type,
        'content': content,
        'content_base64': None,
        'encoding': 'utf-8' if textual else None,
        'error': None,
    }