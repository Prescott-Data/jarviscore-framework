def zoho_people_get_all_employees(auth_info: dict, limit: int = 200) -> dict:
    import requests
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        base_url = auth_info.get("base_url", "https://people.zoho.com").rstrip("/")
        all_records = []
        page = 1
        page_size = min(limit, 200)

        while True:
            resp = requests.get(
                f"{base_url}/people/api/forms/P_EmployeeView/records",
                params={"page": page, "pageSize": page_size},
                headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
                timeout=30
            )
            if resp.status_code != 200:
                return {"success": False, "data": None, "error": f"Get employees failed: {resp.status_code} {resp.text}"}

            data = resp.json()
            # API returns a list directly or wrapped in "data" key
            records = data if isinstance(data, list) else data.get("data", [])
            all_records.extend(records)

            if len(records) < page_size or len(all_records) >= limit:
                break
            page += 1

        return {"success": True, "data": {"employees": all_records, "count": len(all_records)}, "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
