def zoho_books_create_invoice(auth_info: dict, org_id: str, customer_id: str, line_items: list, date: str = None, notes: str = None) -> dict:
    import requests
    # line_items: list of dicts with keys: item_id or name, rate, quantity
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        payload = {"customer_id": customer_id, "line_items": line_items}
        if date:
            payload["date"] = date
        if notes:
            payload["notes"] = notes

        resp = requests.post(
            "https://www.zohoapis.com/books/v3/invoices",
            headers={"Authorization": f"Zoho-oauthtoken {access_token}", "Content-Type": "application/json"},
            params={"organization_id": org_id},
            json=payload,
            timeout=30
        )
        if resp.status_code not in (200, 201):
            return {"success": False, "data": None, "error": f"Create invoice failed: {resp.status_code} {resp.text}"}

        data = resp.json()
        if data.get("code") != 0:
            return {"success": False, "data": None, "error": data.get("message")}

        return {"success": True, "data": data.get("invoice"), "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
