def hubspot_get_contact(auth_info: dict, contact_id: str) -> dict:
    import requests
    _h = {"Authorization": f"Bearer {auth_info.get('access_token', '')}"}
    resp = requests.get(f"https://api.hubapi.com/crm/v3/objects/contacts/{contact_id}", headers=_h, params={"properties": "email,firstname,lastname,company,phone,hs_lead_status"}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return {"success": True, "id": data.get("id"), "properties": data.get("properties", {})}
