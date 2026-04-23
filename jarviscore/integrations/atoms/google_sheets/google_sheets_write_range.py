def google_sheets_write_range(auth_info: dict, spreadsheet_id: str, range_notation: str, values: list, value_input_option: str = "USER_ENTERED") -> dict:
    import requests, urllib.parse
    _base = "https://sheets.googleapis.com/v4/spreadsheets"
    _h = {"Authorization": f"Bearer {auth_info.get('access_token', '')}", "Content-Type": "application/json"}
    body = {"range": range_notation, "majorDimension": "ROWS", "values": values}
    params = {"valueInputOption": value_input_option}
    resp = requests.put(f"{_base}/{spreadsheet_id}/values/{urllib.parse.quote(range_notation)}", headers=_h, json=body, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return {"success": True, "updated_range": data.get("updatedRange"), "updated_rows": data.get("updatedRows"), "updated_cells": data.get("updatedCells")}
