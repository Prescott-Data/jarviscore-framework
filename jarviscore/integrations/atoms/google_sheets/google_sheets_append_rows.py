async def google_sheets_append_rows(spreadsheet_id: str, range_notation: str, values: list) -> dict:
    """Sheets append rows via the google_sheets API."""
    import urllib.parse
    _base = 'https://sheets.googleapis.com/v4/spreadsheets'
    _h = {'Content-Type': 'application/json'}
    body = {'range': range_notation, 'majorDimension': 'ROWS', 'values': values}
    params = {'valueInputOption': 'USER_ENTERED', 'insertDataOption': 'INSERT_ROWS'}
    resp = await nexus_call('POST', f'{_base}/{spreadsheet_id}/values/{urllib.parse.quote(range_notation)}:append', headers=_h, json=body, params=params)
    if not resp['ok']:
        return {'success': False, 'error': resp['body']}
    data = resp['json']
    return {'success': True, 'updates': data.get('updates', {})}
