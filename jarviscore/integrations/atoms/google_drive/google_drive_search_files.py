async def google_drive_search_files(query: str, page_size: int=100, page_token: str=None) -> dict:
    """Search Drive files using a Google Drive query expression."""
    params = {
        'q': query,
        'pageSize': page_size,
        'fields': 'nextPageToken,files(id,name,mimeType,parents,webViewLink,modifiedTime)',
    }
    if page_token:
        params['pageToken'] = page_token
    resp = await nexus_call(
        'GET',
        'https://www.googleapis.com/drive/v3/files',
        provider='google_drive',
        params=params,
    )
    if not resp['ok']:
        return {'success': False, 'error': resp['body']}
    data = resp['json']
    return {
        'success': True,
        'files': data.get('files', []),
        'next_page_token': data.get('nextPageToken'),
    }