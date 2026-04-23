def salesforce_create_lead(auth_info: dict, first_name: str, last_name: str, company: str, email: str = "", phone: str = "", lead_source: str = "Web") -> dict:
    import requests
    instance = auth_info.get("instance_url", "").rstrip("/")
    _h = {"Authorization": f"Bearer {auth_info.get('access_token', '')}", "Content-Type": "application/json"}
    payload = {"FirstName": first_name, "LastName": last_name, "Company": company, "LeadSource": lead_source}
    if email: payload["Email"] = email
    if phone: payload["Phone"] = phone
    resp = requests.post(f"{instance}/services/data/v58.0/sobjects/Lead", headers=_h, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return {"success": True, "id": data.get("id"), "name": f"{first_name} {last_name}", "company": company}
