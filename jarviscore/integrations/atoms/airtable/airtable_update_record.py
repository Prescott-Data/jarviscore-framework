async def airtable_update_record(base_id: str, table_name: str, record_id: str, fields: dict) -> dict:
    """Update specific fields on an existing Airtable record (partial update)."""
    _base = 'https://api.airtable.com/v0'
    _h = {'Content-Type': 'application/json'}

    async def _patch(p, data=None, headers=None):
        _r = await nexus_call('PATCH', f'{_base}{p}', headers={**_h, **(headers or {})}, json=data)
        if not _r['ok']:
            return {'success': False, 'error': _r['body']}
        return _r['json'] if _r['content'] else {}
    return await _patch(f'/{base_id}/{table_name}/{record_id}', {'fields': fields})
