def todoist_close_task(auth_info: dict, task_id: str) -> dict:
    import requests
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        resp = requests.post(
            f"https://api.todoist.com/api/v1/tasks/{task_id}/close",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30
        )
        if resp.status_code != 204:
            return {"success": False, "data": None, "error": f"Close task failed: {resp.status_code} {resp.text}"}

        return {"success": True, "data": {"task_id": task_id, "closed": True}, "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
