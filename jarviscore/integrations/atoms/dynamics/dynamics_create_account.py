def dynamics_create_account(auth_info: dict, org_url: str, name: str, email: str = None, phone: str = None, website: str = None) -> dict:
    import requests
    # org_url: e.g. https://yourorg.api.crm.dynamics.com
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        payload = {"name": name}
        if email:
            payload["emailaddress1"] = email
        if phone:
            payload["telephone1"] = phone
        if website:
            payload["websiteurl"] = website

        resp = requests.post(
            f"{org_url.rstrip('/')}/api/data/v9.2/accounts",
            headers={"Authorization": f"Bearer {access_token}", "OData-MaxVersion": "4.0", "OData-Version": "4.0", "Accept": "application/json", "Content-Type": "application/json", "Prefer": "return=representation"},
            json=payload,
            timeout=30
        )
        if resp.status_code not in (200, 201):
            return {"success": False, "data": None, "error": f"Create account failed: {resp.status_code} {resp.text}"}

        return {"success": True, "data": resp.json(), "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
