def mailchimp_add_subscriber(auth_info: dict, list_id: str, email: str, first_name: str = "", last_name: str = "", status: str = "subscribed") -> dict:
    import requests, hashlib
    server = auth_info.get("server_prefix", "us1")
    _base = f"https://{server}.api.mailchimp.com/3.0"
    _h = {"Content-Type": "application/json"}
    email_hash = hashlib.md5(email.lower().encode()).hexdigest()
    payload = {"email_address": email, "status": status, "merge_fields": {}}
    if first_name: payload["merge_fields"]["FNAME"] = first_name
    if last_name: payload["merge_fields"]["LNAME"] = last_name
    resp = requests.put(f"{_base}/lists/{list_id}/members/{email_hash}", headers=_h, json=payload, auth=("anystring", auth_info.get("api_key", "")), timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return {"success": True, "id": data.get("id"), "email": email, "status": data.get("status")}
