def zoho_shifts_get_shifts(auth_info: dict, org_id: str, start_date: str, end_date: str) -> dict:
    import requests
    # start_date and end_date: YYYY-MM-DD, range cannot exceed 42 days
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        resp = requests.get(
            f"https://shifts.zoho.com/api/v1/{org_id}/shifts",
            headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
            params={"start_date": start_date, "end_date": end_date},
            timeout=30
        )
        if resp.status_code != 200:
            return {"success": False, "data": None, "error": f"Get shifts failed: {resp.status_code} {resp.text}"}

        shifts = resp.json().get("shifts", [])
        return {"success": True, "data": {"shifts": shifts, "count": len(shifts)}, "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
