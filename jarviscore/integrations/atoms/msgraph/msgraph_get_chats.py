def msgraph_get_chats(auth_info: dict, max_results: int = 20) -> dict:
    import requests
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        resp = requests.get(
            "https://graph.microsoft.com/v1.0/me/chats",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"$top": max_results, "$expand": "members"},
            timeout=30
        )
        if resp.status_code != 200:
            return {"success": False, "data": None, "error": f"Get chats failed: {resp.status_code} {resp.text}"}

        chats = resp.json().get("value", [])
        return {"success": True, "data": {"chats": chats, "count": len(chats)}, "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
