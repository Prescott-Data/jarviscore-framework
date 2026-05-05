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

def odoo_get_leads(auth_info: dict, stage: str = None, limit: int = 50) -> dict:
    import requests
    # stage: e.g. 'New', 'Qualified', 'Proposition', 'Won'
    try:
        odoo_url, db, uid, api_key = _authenticate(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        domain = []
        if stage:
            domain.append(["stage_id.name", "=", stage])

        resp = requests.post(
            f"{odoo_url}/jsonrpc",
            json={
                "jsonrpc": "2.0", "method": "call", "id": 2,
                "params": {
                    "service": "object", "method": "execute_kw",
                    "args": [db, uid, api_key, "crm.lead", "search_read",
                        [domain],
                        {"fields": ["id", "name", "partner_name", "email_from", "phone", "stage_id", "expected_revenue", "probability", "user_id", "create_date"], "limit": limit}
                    ]
                }
            },
            timeout=30
        )
        result = resp.json().get("result", [])
        return {"success": True, "data": {"leads": result, "count": len(result)}, "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
