async def airtable_create_record(base_id: str, table_name: str, fields: dict) -> dict:
    """Create record via the airtable API."""
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
    '\n    Create a new record in an Airtable table.\n\n    Args:\n        auth_info: Dict with access_token for the tool\n        base_id:       Airtable base ID (e.g. appXXXXXXXXXXXXXX)\n        table_name:    Table name or table ID\n        fields:        Dict of field names to values (e.g. {"Name": "Acme Corp", "Status": "Active"})\n\n    Returns:\n        The created record including its assigned record ID.\n    '
    return await _post(f'/{base_id}/{table_name}', {'fields': fields})
