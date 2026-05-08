def quickbooks_get_profit_and_loss(auth_info: dict, start_date: str, end_date: str) -> dict:
    import requests
    realm_id = auth_info.get("realm_id", "")
    _h = {"Authorization": f"Bearer {auth_info.get('access_token', '')}", "Accept": "application/json"}
    base = f"https://quickbooks.api.intuit.com/v3/company/{realm_id}"
    params = {"start_date": start_date, "end_date": end_date, "minorversion": "65"}
    resp = requests.get(f"{base}/reports/ProfitAndLoss", headers=_h, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return {"success": True, "report": data.get("Rows", {}), "header": data.get("Header", {})}
