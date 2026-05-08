def _authenticate(auth_info: dict) -> tuple:
    odoo_url = auth_info.get("odoo_url", "").rstrip("/")
    db = auth_info.get("db")
    api_key = auth_info.get("api_key")
    resp = requests.post(
        f"{odoo_url}/jsonrpc",
        json={
            "jsonrpc": "2.0", "method": "call", "id": 1,
            "params": {
                "service": "common", "method": "authenticate",
                "args": [db, auth_info.get("username", "admin"), api_key, {}]
            }
        },
        timeout=30
    )
    resp.raise_for_status()
    uid = resp.json().get("result")
    if not uid:
        raise RuntimeError(f"Odoo authentication failed: {resp.json()}")
    return odoo_url, db, uid, api_key

def odoo_create_lead(auth_info: dict, name: str, partner_name: str = None, email: str = None, phone: str = None, expected_revenue: float = None, description: str = None) -> dict:
    import requests
    try:
        odoo_url, db, uid, api_key = _authenticate(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        values = {"name": name}
        if partner_name:
            values["partner_name"] = partner_name
        if email:
            values["email_from"] = email
        if phone:
            values["phone"] = phone
        if expected_revenue is not None:
            values["expected_revenue"] = expected_revenue
        if description:
            values["description"] = description

        resp = requests.post(
            f"{odoo_url}/jsonrpc",
            json={
                "jsonrpc": "2.0", "method": "call", "id": 2,
                "params": {
                    "service": "object", "method": "execute_kw",
                    "args": [db, uid, api_key, "crm.lead", "create", [values]]
                }
            },
            timeout=30
        )
        lead_id = resp.json().get("result")
        if not lead_id:
            return {"success": False, "data": None, "error": f"Create failed: {resp.json()}"}
        return {"success": True, "data": {"lead_id": lead_id, "name": name}, "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
