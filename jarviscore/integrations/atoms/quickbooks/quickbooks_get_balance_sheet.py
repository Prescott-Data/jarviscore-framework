def quickbooks_get_balance_sheet(auth_info: dict, as_of_date: str) -> dict:
    import requests
    realm_id = auth_info.get("realm_id", "")
    _h = {"Authorization": f"Bearer {auth_info.get('access_token', '')}", "Accept": "application/json"}
    base = f"https://quickbooks.api.intuit.com/v3/company/{realm_id}"
    params = {"date_macro": "This Fiscal Year-to-date", "minorversion": "65"}
    if as_of_date:
        params = {"start_date": as_of_date, "end_date": as_of_date, "minorversion": "65"}
    resp = requests.get(f"{base}/reports/BalanceSheet", headers=_h, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return {"success": True, "report": data.get("Rows", {}), "header": data.get("Header", {})}
