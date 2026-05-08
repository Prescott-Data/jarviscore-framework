def brevo_get_contacts(auth_info: dict, limit: int = 50, offset: int = 0) -> dict:
    import requests
    _h = {"api-key": auth_info.get("api_key", "")}
    resp = requests.get("https://api.brevo.com/v3/contacts", headers=_h, params={"limit": limit, "offset": offset}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return {"success": True, "contacts": data.get("contacts", []), "count": data.get("count", 0)}
