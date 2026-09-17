ATOM_POLICY = {
    'effect': 'write',
    'approval': 'never',
    'idempotency_fields': ['document_id', 'content'],
    'consequence': 'Appends supplied text to one existing Google Docs document.',
}


async def google_drive_append_document_text(document_id: str, content: str) -> dict:
    """Append text to an existing Google Docs document."""
    document = await nexus_call(
        'GET',
        f'https://docs.googleapis.com/v1/documents/{document_id}',
        provider='google_drive',
    )
    if not document['ok']:
        return {'success': False, 'document_id': document_id, 'error': document['body']}
    body = document['json'].get('body', {}).get('content', [])
    end_index = max(
        [int(item.get('endIndex') or 1) for item in body] or [1]
    )
    updated = await nexus_call(
        'POST',
        f'https://docs.googleapis.com/v1/documents/{document_id}:batchUpdate',
        provider='google_drive',
        headers={'Content-Type': 'application/json'},
        json={
            'requests': [{
                'insertText': {
                    'location': {'index': max(1, end_index - 1)},
                    'text': content,
                },
            }],
        },
    )
    if not updated['ok']:
        return {'success': False, 'document_id': document_id, 'error': updated['body']}
    return {
        'success': True,
        'document_id': document_id,
        'inserted_characters': len(content),
        'error': None,
    }