def todoist_get_projects(auth_info: dict) -> dict:
    import requests
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        resp = requests.get(
            "https://api.todoist.com/api/v1/projects",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30
        )
        if resp.status_code != 200:
            return {"success": False, "data": None, "error": f"Get projects failed: {resp.status_code} {resp.text}"}

        projects = resp.json().get("results", [])
        return {"success": True, "data": {"projects": projects, "count": len(projects)}, "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
