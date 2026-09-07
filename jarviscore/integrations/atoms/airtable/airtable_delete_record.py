async def airtable_delete_record(base_id: str, table_name: str, record_id: str) -> dict:
    """Delete record via the airtable API."""
    _base = 'https://api.airtable.com/v0'
    _h = {'Content-Type': 'application/json'}

    async def _get(p, params=None, headers=None):
        _r = await nexus_call('GET', f'{_base}{p}', headers={**_h, **(headers or {})}, params=params or {})
        if not _r['ok']:
            return {'success': False, 'error': _r['body']}
        return _r['json']

    async def _post(p, data=None, headers=None):
        _r = await nexus_call('POST', f'{_base}{p}', headers={**_h, **(headers or {})}, json=data)
        if not _r['ok']:
            return {'success': False, 'error': _r['body']}
        return _r['json']

    async def _put(p, data=None, headers=None):
        _r = await nexus_call('PUT', f'{_base}{p}', headers={**_h, **(headers or {})}, json=data)
        if not _r['ok']:
            return {'success': False, 'error': _r['body']}
        return _r['json']

    async def _patch(p, data=None, headers=None):
        _r = await nexus_call('PATCH', f'{_base}{p}', headers={**_h, **(headers or {})}, json=data)
        if not _r['ok']:
            return {'success': False, 'error': _r['body']}
        return _r['json'] if _r['content'] else {}

    async def _delete(p, headers=None):
        _r = await nexus_call('DELETE', f'{_base}{p}', headers={**_h, **(headers or {})})
        if not _r['ok']:
            return {'success': False, 'error': _r['body']}
        return _r['json'] if _r['content'] else {}
    '\n    Delete a record from an Airtable table.\n\n    Args:\n        auth_info: Dict with access_token for the tool\n        base_id:       Airtable base ID (e.g. appXXXXXXXXXXXXXX)\n        table_name:    Table name or table ID\n        record_id:     Record ID to delete (e.g. recXXXXXXXXXXXXXX)\n\n    Returns:\n        Confirmation payload with deleted record ID and deleted=True.\n    '
    return await _delete(f'/{base_id}/{table_name}/{record_id}')
