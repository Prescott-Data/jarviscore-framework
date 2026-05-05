def discord_get_connections(auth_info: dict) -> dict:
    import requests
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        resp = requests.get(
            "https://discord.com/api/v10/users/@me/connections",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30
        )
        if resp.status_code != 200:
            return {"success": False, "data": None, "error": f"Get connections failed: {resp.status_code} {resp.text}"}

        connections = resp.json()
        return {"success": True, "data": {"connections": connections, "count": len(connections)}, "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
