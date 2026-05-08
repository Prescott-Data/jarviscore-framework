def clickup_create_task(auth_info: dict, list_id: str, name: str, description: str = None, priority: int = None, status: str = None) -> dict:
    import requests
    # priority: 1=urgent, 2=high, 3=normal, 4=low
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        payload = {"name": name}
        if description:
            payload["description"] = description
        if priority:
            payload["priority"] = priority
        if status:
            payload["status"] = status

        resp = requests.post(
            f"https://api.clickup.com/api/v2/list/{list_id}/task",
            json=payload,
            headers={"Authorization": access_token, "Content-Type": "application/json"},
            timeout=30
        )
        if resp.status_code not in (200, 201):
            return {"success": False, "data": None, "error": f"Create task failed: {resp.status_code} {resp.text}"}

        return {"success": True, "data": resp.json(), "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
