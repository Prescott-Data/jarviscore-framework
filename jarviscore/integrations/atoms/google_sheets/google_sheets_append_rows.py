def google_sheets_append_rows(auth_info: dict, spreadsheet_id: str, range_notation: str, values: list) -> dict:
    import requests, urllib.parse
    _base = "https://sheets.googleapis.com/v4/spreadsheets"
    _h = {"Authorization": f"Bearer {auth_info.get('access_token', '')}", "Content-Type": "application/json"}
    body = {"range": range_notation, "majorDimension": "ROWS", "values": values}
    params = {"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS"}
    resp = requests.post(f"{_base}/{spreadsheet_id}/values/{urllib.parse.quote(range_notation)}:append", headers=_h, json=body, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return {"success": True, "updates": data.get("updates", {})}
