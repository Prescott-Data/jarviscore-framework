def todoist_create_project(auth_info: dict, name: str, color: str = None, is_favorite: bool = False) -> dict:
    import requests
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        payload = {"name": name, "is_favorite": is_favorite}
        if color:
            payload["color"] = color

        resp = requests.post(
            "https://api.todoist.com/api/v1/projects",
            json=payload,
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            timeout=30
        )
        if resp.status_code not in (200, 201):
            return {"success": False, "data": None, "error": f"Create project failed: {resp.status_code} {resp.text}"}

        data = resp.json()
        return {"success": True, "data": data.get("results", data), "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
