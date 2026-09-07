async def google_sheets_get_spreadsheet(spreadsheet_id: str) -> dict:
    """Sheets get spreadsheet via the google_sheets API."""
    _h = {}
    resp = await nexus_call('GET', f'https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}', headers=_h, params={'includeGridData': 'false'})
    if not resp['ok']:
        return {'success': False, 'error': resp['body']}
    data = resp['json']
    sheets = [{'id': s['properties']['sheetId'], 'title': s['properties']['title'], 'row_count': s['properties']['gridProperties']['rowCount']} for s in data.get('sheets', [])]
    return {'success': True, 'spreadsheet_id': spreadsheet_id, 'title': data.get('properties', {}).get('title'), 'sheets': sheets}
