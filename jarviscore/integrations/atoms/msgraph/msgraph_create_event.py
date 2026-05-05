def msgraph_create_event(auth_info: dict, subject: str, start_datetime: str, end_datetime: str, timezone: str = "UTC", attendees: list = None, body: str = None, location: str = None) -> dict:
    import requests
    # start_datetime and end_datetime: ISO 8601 e.g. 2026-03-28T10:00:00
    # attendees: list of email address strings
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        payload = {
            "subject": subject,
            "start": {"dateTime": start_datetime, "timeZone": timezone},
            "end": {"dateTime": end_datetime, "timeZone": timezone}
        }
        if attendees:
            payload["attendees"] = [{"emailAddress": {"address": a}, "type": "required"} for a in attendees]
        if body:
            payload["body"] = {"contentType": "Text", "content": body}
        if location:
            payload["location"] = {"displayName": location}

        resp = requests.post(
            "https://graph.microsoft.com/v1.0/me/events",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json=payload,
            timeout=30
        )
        if resp.status_code != 201:
            return {"success": False, "data": None, "error": f"Create event failed: {resp.status_code} {resp.text}"}

        return {"success": True, "data": resp.json(), "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
