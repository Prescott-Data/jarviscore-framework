def zoho_people_get_form_data(auth_info: dict, form_link_name: str, search_field: str = None, search_value: str = None) -> dict:
    import requests
    # form_link_name: e.g. "P_EmployeeView", "P_LeaveGrantView", custom form names
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        base_url = auth_info.get("base_url", "https://people.zoho.com").rstrip("/")
        params = {}
        if search_field and search_value:
            params["searchField"] = search_field
            params["searchValue"] = search_value

        resp = requests.get(
            f"{base_url}/people/api/forms/{form_link_name}/records",
            params=params,
            headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
            timeout=30
        )
        if resp.status_code != 200:
            return {"success": False, "data": None, "error": f"Get form data failed: {resp.status_code} {resp.text}"}

        data = resp.json()
        records = data if isinstance(data, list) else data.get("data", data)
        return {"success": True, "data": {"records": records, "form": form_link_name}, "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
