def stripe_get_balance(auth_info: dict) -> dict:
    import requests
    _h = {"Authorization": f"Bearer {auth_info.get('api_key', '')}"}
    resp = requests.get("https://api.stripe.com/v1/balance", headers=_h, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    available = [{"currency": b["currency"], "amount": b["amount"]} for b in data.get("available", [])]
    pending = [{"currency": b["currency"], "amount": b["amount"]} for b in data.get("pending", [])]
    return {"success": True, "available": available, "pending": pending}
