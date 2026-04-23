def stripe_list_invoices(auth_info: dict, customer_id: str = None, status: str = None, limit: int = 20) -> dict:
    import requests
    _h = {"Authorization": f"Bearer {auth_info.get('api_key', '')}"}
    params = {"limit": limit}
    if customer_id: params["customer"] = customer_id
    if status: params["status"] = status
    resp = requests.get("https://api.stripe.com/v1/invoices", headers=_h, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    invoices = [{"id": inv["id"], "customer": inv.get("customer"), "amount_due": inv.get("amount_due"), "currency": inv.get("currency"), "status": inv.get("status"), "due_date": inv.get("due_date")} for inv in data.get("data", [])]
    return {"success": True, "invoices": invoices, "has_more": data.get("has_more")}
