def zoho_books_create_contact(auth_info: dict, org_id: str, contact_name: str, contact_type: str = "customer", email: str = None, phone: str = None) -> dict:
    import requests
    # contact_type: customer or vendor
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        payload = {"contact_name": contact_name, "contact_type": contact_type}
        if email:
            payload["email"] = email
        if phone:
            payload["phone"] = phone

        resp = requests.post(
            "https://www.zohoapis.com/books/v3/contacts",
            headers={"Authorization": f"Zoho-oauthtoken {access_token}", "Content-Type": "application/json"},
            params={"organization_id": org_id},
            json=payload,
            timeout=30
        )
        if resp.status_code not in (200, 201):
            return {"success": False, "data": None, "error": f"Create contact failed: {resp.status_code} {resp.text}"}

        data = resp.json()
        if data.get("code") != 0:
            return {"success": False, "data": None, "error": data.get("message")}

        return {"success": True, "data": data.get("contact"), "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
