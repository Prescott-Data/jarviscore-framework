def todoist_update_task(auth_info: dict, task_id: str, content: str = None, due_string: str = None, priority: int = None) -> dict:
    import requests
    # priority: 1=normal, 2=medium, 3=high, 4=urgent
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        payload = {}
        if content:
            payload["content"] = content
        if due_string:
            payload["due_string"] = due_string
        if priority:
            payload["priority"] = priority

        resp = requests.post(
            f"https://api.todoist.com/api/v1/tasks/{task_id}",
            json=payload,
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            timeout=30
        )
        if resp.status_code != 200:
            return {"success": False, "data": None, "error": f"Update task failed: {resp.status_code} {resp.text}"}

        data = resp.json()
        return {"success": True, "data": data.get("results", data), "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
