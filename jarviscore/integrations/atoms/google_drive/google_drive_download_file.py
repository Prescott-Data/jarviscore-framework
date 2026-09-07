async def google_drive_download_file(file_id: str, destination_path: str) -> dict:
    """Download a Drive file to a local path. https://developers.google.com/drive/api/reference/rest/v3/files/get"""
    import os
    response = await nexus_call('GET', f'https://www.googleapis.com/drive/v3/files/{file_id}', params={'alt': 'media'})
    if not response['ok']:
        return {'success': False, 'file_id': file_id, 'data': None, 'error': f"Download failed: {response['status_code']} {response['body']}"}
    directory = os.path.dirname(destination_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(destination_path, 'wb') as handle:
        handle.write(response['content'])
    return {'success': True, 'file_id': file_id, 'data': {'destination_path': destination_path}, 'error': None}
