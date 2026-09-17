async def airtable_list_records(base_id: str, table_name: str, filter_formula: str=None, max_records: int=None, view: str=None) -> list:
    """List records from an Airtable table."""
    _base = 'https://api.airtable.com/v0'
    _h = {'Content-Type': 'application/json'}

    async def _get(p, params=None, headers=None):
        _r = await nexus_call('GET', f'{_base}{p}', headers={**_h, **(headers or {})}, params=params or {})
        if not _r['ok']:
            return {'success': False, 'error': _r['body']}
        return _r['json']
    params = {}
    if filter_formula:
        params['filterByFormula'] = filter_formula
    if max_records:
        params['maxRecords'] = max_records
    if view:
        params['view'] = view
    all_records = []
    offset = None
    while True:
        if offset:
            params['offset'] = offset
        result = await _get(f'/{base_id}/{table_name}', params=params)
        all_records.extend(result.get('records', []))
        offset = result.get('offset')
        if not offset:
            break
    return all_records
