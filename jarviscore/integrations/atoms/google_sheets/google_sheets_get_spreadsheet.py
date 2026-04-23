def google_sheets_get_spreadsheet(auth_info: dict, spreadsheet_id: str) -> dict:
    import requests
    _h = {"Authorization": f"Bearer {auth_info.get('access_token', '')}"}
    resp = requests.get(f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}", headers=_h, params={"includeGridData": "false"}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    sheets = [{"id": s["properties"]["sheetId"], "title": s["properties"]["title"], "row_count": s["properties"]["gridProperties"]["rowCount"]} for s in data.get("sheets", [])]
    return {"success": True, "spreadsheet_id": spreadsheet_id, "title": data.get("properties", {}).get("title"), "sheets": sheets}
