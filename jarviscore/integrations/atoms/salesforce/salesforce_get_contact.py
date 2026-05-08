def salesforce_get_contact(auth_info: dict, contact_id: str) -> dict:
    import requests
    instance = auth_info.get("instance_url", "").rstrip("/")
    _h = {"Authorization": f"Bearer {auth_info.get('access_token', '')}"}
    resp = requests.get(f"{instance}/services/data/v58.0/sobjects/Contact/{contact_id}", headers=_h, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return {"success": True, "id": data.get("Id"), "name": data.get("Name"), "email": data.get("Email"), "account": data.get("AccountId"), "phone": data.get("Phone")}
