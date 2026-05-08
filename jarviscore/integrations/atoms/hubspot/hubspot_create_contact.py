def hubspot_create_contact(auth_info: dict, email: str, first_name: str = "", last_name: str = "", company: str = "", phone: str = "") -> dict:
    import requests
    _h = {"Authorization": f"Bearer {auth_info.get('access_token', '')}", "Content-Type": "application/json"}
    props = {"email": email}
    if first_name: props["firstname"] = first_name
    if last_name: props["lastname"] = last_name
    if company: props["company"] = company
    if phone: props["phone"] = phone
    resp = requests.post("https://api.hubapi.com/crm/v3/objects/contacts", headers=_h, json={"properties": props}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return {"success": True, "id": data.get("id"), "email": email, "created_at": data.get("createdAt")}
