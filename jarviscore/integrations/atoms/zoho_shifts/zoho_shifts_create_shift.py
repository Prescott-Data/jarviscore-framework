def zoho_shifts_create_shift(auth_info: dict, org_id: str, schedule_id: str, start_time: str, end_time: str, employee_id: str = None, position_id: str = None, notes: str = None) -> dict:
    import requests
    # start_time and end_time: ISO 8601 UTC e.g. 2026-03-28T06:00:00Z
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        payload = {
            "schedule_id": schedule_id,
            "start_time": start_time,
            "end_time": end_time
        }
        if employee_id:
            payload["employee_id"] = employee_id
        if position_id:
            payload["position_id"] = position_id
        if notes:
            payload["notes"] = notes

        resp = requests.post(
            f"https://shifts.zoho.com/api/v1/{org_id}/shifts",
            headers={"Authorization": f"Zoho-oauthtoken {access_token}", "Content-Type": "application/json"},
            json=payload,
            timeout=30
        )
        if resp.status_code != 200:
            return {"success": False, "data": None, "error": f"Create shift failed: {resp.status_code} {resp.text}"}

        return {"success": True, "data": resp.json(), "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
