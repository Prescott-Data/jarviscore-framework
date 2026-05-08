def msgraph_get_events(auth_info: dict, max_results: int = 20, start_datetime: str = None, end_datetime: str = None) -> dict:
    import requests
    # start_datetime and end_datetime: ISO 8601 e.g. 2026-03-28T00:00:00Z
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        params = {"$top": max_results, "$orderby": "start/dateTime", "$select": "id,subject,start,end,location,organizer,isOnlineMeeting"}
        if start_datetime and end_datetime:
            params["$filter"] = f"start/dateTime ge '{start_datetime}' and end/dateTime le '{end_datetime}'"

        resp = requests.get(
            "https://graph.microsoft.com/v1.0/me/events",
            headers={"Authorization": f"Bearer {access_token}", "Prefer": 'outlook.timezone="UTC"'},
            params=params,
            timeout=30
        )
        if resp.status_code != 200:
            return {"success": False, "data": None, "error": f"Get events failed: {resp.status_code} {resp.text}"}

        events = resp.json().get("value", [])
        return {"success": True, "data": {"events": events, "count": len(events)}, "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
