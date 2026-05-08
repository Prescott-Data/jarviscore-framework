def zoho_people_get_attendance(auth_info: dict, employee_id: str, from_date: str, to_date: str) -> dict:
    import requests
    # from_date, to_date: "MM/dd/yyyy" format
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        base_url = auth_info.get("base_url", "https://people.zoho.com").rstrip("/")
        # empId must be the Employee ID code (e.g. "S20"), not record ID or email
        resp = requests.get(
            f"{base_url}/people/api/attendance/getAttendanceEntries",
            params={"empId": employee_id, "startDate": from_date, "endDate": to_date},
            headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
            timeout=30
        )
        if resp.status_code != 200:
            return {"success": False, "data": None, "error": f"Get attendance failed: {resp.status_code} {resp.text}"}

        return {"success": True, "data": resp.json(), "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
