def google_sheets_read_range(auth_info: dict, spreadsheet_id: str, range_notation: str) -> dict:
    import requests
    _base = "https://sheets.googleapis.com/v4/spreadsheets"
    _h = {"Authorization": f"Bearer {auth_info.get('access_token', '')}"}
    import urllib.parse
    resp = requests.get(f"{_base}/{spreadsheet_id}/values/{urllib.parse.quote(range_notation)}", headers=_h, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return {"success": True, "range": data.get("range"), "values": data.get("values", []), "rows": len(data.get("values", []))}
