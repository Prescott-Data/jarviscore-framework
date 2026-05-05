def msgraph_delete_event(auth_info: dict, event_id: str) -> dict:
    import requests
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        resp = requests.delete(
            f"https://graph.microsoft.com/v1.0/me/events/{event_id}",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30
        )
        if resp.status_code != 204:
            return {"success": False, "data": None, "error": f"Delete event failed: {resp.status_code} {resp.text}"}

        return {"success": True, "data": {"event_id": event_id, "deleted": True}, "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
