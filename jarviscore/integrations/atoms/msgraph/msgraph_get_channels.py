def msgraph_get_channels(auth_info: dict, team_id: str) -> dict:
    import requests
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        resp = requests.get(
            f"https://graph.microsoft.com/v1.0/teams/{team_id}/channels",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30
        )
        if resp.status_code != 200:
            return {"success": False, "data": None, "error": f"Get channels failed: {resp.status_code} {resp.text}"}

        channels = resp.json().get("value", [])
        return {"success": True, "data": {"channels": channels, "count": len(channels)}, "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
