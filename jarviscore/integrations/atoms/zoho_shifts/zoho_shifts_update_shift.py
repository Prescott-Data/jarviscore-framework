def zoho_shifts_update_shift(auth_info: dict, org_id: str, shift_id: str, start_time: str = None, end_time: str = None, employee_id: str = None, notes: str = None) -> dict:
    import requests
    # start_time and end_time: ISO 8601 UTC e.g. 2026-03-28T06:00:00Z
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        payload = {}
        if start_time:
            payload["start_time"] = start_time
        if end_time:
            payload["end_time"] = end_time
        if employee_id:
            payload["employee_id"] = employee_id
        if notes is not None:
            payload["notes"] = notes

        resp = requests.put(
            f"https://shifts.zoho.com/api/v1/{org_id}/shifts/{shift_id}",
            headers={"Authorization": f"Zoho-oauthtoken {access_token}", "Content-Type": "application/json"},
            json=payload,
            timeout=30
        )
        if resp.status_code != 200:
            return {"success": False, "data": None, "error": f"Update shift failed: {resp.status_code} {resp.text}"}

        return {"success": True, "data": resp.json(), "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
