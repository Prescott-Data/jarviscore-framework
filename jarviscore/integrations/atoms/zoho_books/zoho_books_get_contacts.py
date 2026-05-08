def zoho_books_get_contacts(auth_info: dict, org_id: str, contact_type: str = None) -> dict:
    import requests
    # contact_type: customer or vendor
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        params = {"organization_id": org_id}
        if contact_type:
            params["contact_type"] = contact_type

        resp = requests.get(
            "https://www.zohoapis.com/books/v3/contacts",
            headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
            params=params,
            timeout=30
        )
        if resp.status_code != 200:
            return {"success": False, "data": None, "error": f"Get contacts failed: {resp.status_code} {resp.text}"}

        data = resp.json()
        if data.get("code") != 0:
            return {"success": False, "data": None, "error": data.get("message")}

        contacts = data.get("contacts", [])
        return {"success": True, "data": {"contacts": contacts, "count": len(contacts)}, "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
