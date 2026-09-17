async def google_drive_get_document(document_id: str) -> dict:
    """Read a Google Docs document with its text and structural metadata."""
    resp = await nexus_call(
        'GET',
        f'https://docs.googleapis.com/v1/documents/{document_id}',
        provider='google_drive',
    )
    if not resp['ok']:
        return {
            'success': False,
            'document_id': document_id,
            'title': None,
            'text': None,
            'paragraph_count': 0,
            'content_length': 0,
            'error': resp['body'],
        }
    document = resp['json'] or {}
    paragraphs = []
    for item in document.get('body', {}).get('content', []):
        paragraph = item.get('paragraph')
        if not isinstance(paragraph, dict):
            continue
        paragraphs.append(''.join(
            str((element.get('textRun') or {}).get('content') or '')
            for element in paragraph.get('elements', [])
        ))
    text = ''.join(paragraphs)
    return {
        'success': True,
        'document_id': document_id,
        'title': document.get('title'),
        'text': text,
        'paragraph_count': len(paragraphs),
        'content_length': len(text.strip()),
        'error': None,
    }
