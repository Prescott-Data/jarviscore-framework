def msgraph_get_teams(auth_info: dict) -> dict:
    import requests
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        resp = requests.get(
            "https://graph.microsoft.com/v1.0/me/joinedTeams",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30
        )
        if resp.status_code != 200:
            return {"success": False, "data": None, "error": f"Get teams failed: {resp.status_code} {resp.text}"}

        teams = resp.json().get("value", [])
        return {"success": True, "data": {"teams": teams, "count": len(teams)}, "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
