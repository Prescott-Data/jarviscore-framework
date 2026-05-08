def msgraph_create_meeting(auth_info: dict, subject: str, start_datetime: str, end_datetime: str, timezone: str = "UTC", participants: list = None) -> dict:
    import requests
    # start_datetime and end_datetime: ISO 8601 e.g. 2026-03-28T10:00:00
    # participants: list of email address strings
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        payload = {
            "subject": subject,
            "startDateTime": f"{start_datetime}",
            "endDateTime": f"{end_datetime}",
        }
        if participants:
            payload["participants"] = {
                "attendees": [{"upn": p} for p in participants]
            }

        resp = requests.post(
            "https://graph.microsoft.com/v1.0/me/onlineMeetings",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json=payload,
            timeout=30
        )
        if resp.status_code != 201:
            return {"success": False, "data": None, "error": f"Create meeting failed: {resp.status_code} {resp.text}"}

        data = resp.json()
        return {"success": True, "data": {"meeting_id": data.get("id"), "join_url": data.get("joinWebUrl"), "subject": data.get("subject")}, "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
