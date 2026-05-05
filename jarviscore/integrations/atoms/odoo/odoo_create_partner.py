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

def odoo_create_partner(auth_info: dict, name: str, email: str = None, phone: str = None, is_company: bool = False, street: str = None, city: str = None) -> dict:
    import requests
    try:
        odoo_url, db, uid, api_key = _authenticate(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        values = {"name": name, "is_company": is_company}
        if email:
            values["email"] = email
        if phone:
            values["phone"] = phone
        if street:
            values["street"] = street
        if city:
            values["city"] = city

        resp = requests.post(
            f"{odoo_url}/jsonrpc",
            json={
                "jsonrpc": "2.0", "method": "call", "id": 2,
                "params": {
                    "service": "object", "method": "execute_kw",
                    "args": [db, uid, api_key, "res.partner", "create", [values]]
                }
            },
            timeout=30
        )
        partner_id = resp.json().get("result")
        if not partner_id:
            return {"success": False, "data": None, "error": f"Create failed: {resp.json()}"}
        return {"success": True, "data": {"partner_id": partner_id, "name": name}, "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
