def stripe_list_charges(auth_info: dict, customer_id: str = None, limit: int = 20, created_gte: int = None) -> dict:
    import requests
    _h = {"Authorization": f"Bearer {auth_info.get('api_key', '')}"}
    params = {"limit": limit}
    if customer_id: params["customer"] = customer_id
    if created_gte: params["created[gte]"] = created_gte
    resp = requests.get("https://api.stripe.com/v1/charges", headers=_h, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    charges = [{"id": c["id"], "amount": c.get("amount"), "currency": c.get("currency"), "status": c.get("status"), "customer": c.get("customer"), "description": c.get("description"), "created": c.get("created")} for c in data.get("data", [])]
    return {"success": True, "charges": charges, "has_more": data.get("has_more")}
