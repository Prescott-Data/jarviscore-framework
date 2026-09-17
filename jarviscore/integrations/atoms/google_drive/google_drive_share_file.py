ATOM_POLICY = {
    "effect": "write",
    "approval": "required",
    "idempotency_fields": ["file_id", "email", "role"],
    "consequence": "Grants one recipient access to a Google Drive file.",
}


async def google_drive_share_file(file_id: str, email: str, role: str='reader') -> dict:
    """Drive share file via the google_drive API."""
    try:
        permission = {'type': 'user', 'role': role, 'emailAddress': email}
        resp = await nexus_call(
            'POST',
            f'https://www.googleapis.com/drive/v3/files/{file_id}/permissions',
            provider='google_drive',
            json=permission,
        )
        if not resp['ok']:
            return {'success': False, 'file_id': file_id, 'data': None, 'error': resp['body']}
        return {'success': True, 'file_id': file_id, 'data': resp['json'], 'error': None}
    except Exception as e:
        return {'success': False, 'file_id': file_id, 'data': None, 'error': str(e)}
