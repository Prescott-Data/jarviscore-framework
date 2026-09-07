async def google_sheets_write_range(spreadsheet_id: str, range_notation: str, values: list, value_input_option: str='USER_ENTERED') -> dict:
    """Sheets write range via the google_sheets API."""
    import urllib.parse
    _base = 'https://sheets.googleapis.com/v4/spreadsheets'
    _h = {'Content-Type': 'application/json'}
    body = {'range': range_notation, 'majorDimension': 'ROWS', 'values': values}
    params = {'valueInputOption': value_input_option}
    resp = await nexus_call('PUT', f'{_base}/{spreadsheet_id}/values/{urllib.parse.quote(range_notation)}', headers=_h, json=body, params=params)
    if not resp['ok']:
        return {'success': False, 'error': resp['body']}
    data = resp['json']
    return {'success': True, 'updated_range': data.get('updatedRange'), 'updated_rows': data.get('updatedRows'), 'updated_cells': data.get('updatedCells')}
