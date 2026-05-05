def zoho_books_get_contact(auth_info: dict, org_id: str, contact_id: str) -> dict:
    import requests
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        resp = requests.get(
            f"https://www.zohoapis.com/books/v3/contacts/{contact_id}",
            headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
            params={"organization_id": org_id},
            timeout=30
        )
        if resp.status_code != 200:
            return {"success": False, "data": None, "error": f"Get contact failed: {resp.status_code} {resp.text}"}

        data = resp.json()
        if data.get("code") != 0:
            return {"success": False, "data": None, "error": data.get("message")}

        return {"success": True, "data": data.get("contact"), "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
