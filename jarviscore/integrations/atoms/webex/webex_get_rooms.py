def webex_get_rooms(auth_info: dict, max_results: int = 50) -> dict:
    import requests
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        resp = requests.get(
            "https://webexapis.com/v1/rooms",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"max": max_results},
            timeout=30
        )
        if resp.status_code != 200:
            return {"success": False, "data": None, "error": f"Get rooms failed: {resp.status_code} {resp.text}"}

        rooms = resp.json().get("items", [])
        return {"success": True, "data": {"rooms": rooms, "count": len(rooms)}, "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
