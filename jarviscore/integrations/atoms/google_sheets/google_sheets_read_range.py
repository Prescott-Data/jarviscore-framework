async def google_sheets_read_range(spreadsheet_id: str, range_notation: str) -> dict:
    """Sheets read range via the google_sheets API."""
    _base = 'https://sheets.googleapis.com/v4/spreadsheets'
    _h = {}
    import urllib.parse
    resp = await nexus_call('GET', f'{_base}/{spreadsheet_id}/values/{urllib.parse.quote(range_notation)}', headers=_h)
    if not resp['ok']:
        return {'success': False, 'error': resp['body']}
    data = resp['json']
    return {'success': True, 'range': data.get('range'), 'values': data.get('values', []), 'rows': len(data.get('values', []))}
