def brevo_create_contact(auth_info: dict, email: str, first_name: str = "", last_name: str = "", list_ids: list = None) -> dict:
    import requests
    _h = {"api-key": auth_info.get("api_key", ""), "Content-Type": "application/json"}
    payload = {"email": email, "attributes": {}}
    if first_name:
        payload["attributes"]["FIRSTNAME"] = first_name
    if last_name:
        payload["attributes"]["LASTNAME"] = last_name
    if list_ids:
        payload["listIds"] = list_ids
    resp = requests.post("https://api.brevo.com/v3/contacts", headers=_h, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return {"success": True, "id": data.get("id"), "email": email}
