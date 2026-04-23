def quickbooks_list_expenses(auth_info: dict, start_date: str = None, end_date: str = None, limit: int = 50) -> dict:
    import requests
    realm_id = auth_info.get("realm_id", "")
    _h = {"Authorization": f"Bearer {auth_info.get('access_token', '')}", "Accept": "application/json"}
    base = f"https://quickbooks.api.intuit.com/v3/company/{realm_id}"
    where_clause = "WHERE TxnDate >= '{}' AND TxnDate <= '{}'".format(start_date, end_date) if start_date and end_date else ""
    query = f"SELECT * FROM Purchase {where_clause} MAXRESULTS {limit}"
    resp = requests.get(f"{base}/query", headers=_h, params={"query": query, "minorversion": "65"}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    purchases = data.get("QueryResponse", {}).get("Purchase", [])
    return {"success": True, "expenses": [{"id": p.get("Id"), "date": p.get("TxnDate"), "amount": p.get("TotalAmt"), "account": p.get("AccountRef", {}).get("name"), "memo": p.get("PrivateNote")} for p in purchases], "count": len(purchases)}
