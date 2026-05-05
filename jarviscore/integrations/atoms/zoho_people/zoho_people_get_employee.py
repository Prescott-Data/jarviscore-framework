def zoho_people_get_employee(auth_info: dict, employee_id: str) -> dict:
    import requests
    # employee_id: Zoho People record ID or email address
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        base_url = auth_info.get("base_url", "https://people.zoho.com").rstrip("/")

        # search by email if @ present, otherwise treat as record ID
        if "@" in employee_id:
            params = {"searchField": "Email", "searchValue": employee_id}
        else:
            params = {"searchField": "Zoho_ID", "searchValue": employee_id}

        resp = requests.get(
            f"{base_url}/people/api/forms/P_EmployeeView/records",
            params=params,
            headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
            timeout=30
        )

        if resp.status_code != 200:
            return {"success": False, "data": None, "error": f"Get employee failed: {resp.status_code} {resp.text}"}

        data = resp.json()
        records = data if isinstance(data, list) else data.get("data", data)
        return {"success": True, "data": records, "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
