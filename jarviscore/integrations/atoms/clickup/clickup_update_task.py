def clickup_update_task(auth_info: dict, task_id: str, name: str = None, description: str = None, status: str = None, priority: int = None) -> dict:
    import requests
    # priority: 1=urgent, 2=high, 3=normal, 4=low
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        payload = {}
        if name:
            payload["name"] = name
        if description:
            payload["description"] = description
        if status:
            payload["status"] = status
        if priority:
            payload["priority"] = priority

        resp = requests.put(
            f"https://api.clickup.com/api/v2/task/{task_id}",
            json=payload,
            headers={"Authorization": access_token, "Content-Type": "application/json"},
            timeout=30
        )
        if resp.status_code != 200:
            return {"success": False, "data": None, "error": f"Update task failed: {resp.status_code} {resp.text}"}

        return {"success": True, "data": resp.json(), "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
