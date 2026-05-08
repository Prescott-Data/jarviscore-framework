def webex_get_messages(auth_info: dict, room_id: str, max_results: int = 50) -> dict:
    import requests
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        resp = requests.get(
            "https://webexapis.com/v1/messages",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"roomId": room_id, "max": max_results},
            timeout=30
        )
        if resp.status_code != 200:
            return {"success": False, "data": None, "error": f"Get messages failed: {resp.status_code} {resp.text}"}

        messages = resp.json().get("items", [])
        return {"success": True, "data": {"messages": messages, "count": len(messages)}, "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
