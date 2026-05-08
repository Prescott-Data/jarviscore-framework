def stripe_get_customer(auth_info: dict, customer_id: str) -> dict:
    import requests
    _h = {"Authorization": f"Bearer {auth_info.get('api_key', '')}"}
    resp = requests.get(f"https://api.stripe.com/v1/customers/{customer_id}", headers=_h, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return {"success": True, "id": data.get("id"), "email": data.get("email"), "name": data.get("name"), "currency": data.get("currency"), "balance": data.get("balance"), "created": data.get("created")}
