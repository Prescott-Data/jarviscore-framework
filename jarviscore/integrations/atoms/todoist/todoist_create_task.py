def todoist_create_task(auth_info: dict, content: str, project_id: str = None, due_string: str = None, priority: int = 1) -> dict:
    import requests
    # priority: 1=normal, 2=medium, 3=high, 4=urgent
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        payload = {"content": content, "priority": priority}
        if project_id:
            payload["project_id"] = project_id
        if due_string:
            payload["due_string"] = due_string

        resp = requests.post(
            "https://api.todoist.com/api/v1/tasks",
            json=payload,
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            timeout=30
        )
        if resp.status_code not in (200, 201):
            return {"success": False, "data": None, "error": f"Create task failed: {resp.status_code} {resp.text}"}

        return {"success": True, "data": resp.json().get("results", resp.json()), "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
