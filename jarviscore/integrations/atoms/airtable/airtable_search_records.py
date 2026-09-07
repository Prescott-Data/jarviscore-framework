async def airtable_search_records(base_id: str, table_name: str, field_name: str, value: str) -> list:
    """Search for records in an Airtable table where a specific field matches a value."""
    _base = 'https://api.airtable.com/v0'
    _h = {'Content-Type': 'application/json'}

    async def _get(p, params=None, headers=None):
        _r = await nexus_call('GET', f'{_base}{p}', headers={**_h, **(headers or {})}, params=params or {})
        if not _r['ok']:
            return {'success': False, 'error': _r['body']}
        return _r['json']
    filter_formula = f"{{{field_name}}}='{value}'"
    result = await _get(f'/{base_id}/{table_name}', params={'filterByFormula': filter_formula})
    return result.get('records', [])
