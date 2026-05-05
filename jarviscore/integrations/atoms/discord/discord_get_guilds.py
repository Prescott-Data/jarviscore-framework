def discord_get_guilds(auth_info: dict) -> dict:
    import requests
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        resp = requests.get(
            "https://discord.com/api/v10/users/@me/guilds",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30
        )
        if resp.status_code != 200:
            return {"success": False, "data": None, "error": f"Get guilds failed: {resp.status_code} {resp.text}"}

        guilds = resp.json()
        return {"success": True, "data": {"guilds": guilds, "count": len(guilds)}, "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
