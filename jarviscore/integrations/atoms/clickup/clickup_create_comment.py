def clickup_create_comment(auth_info: dict, task_id: str, comment_text: str) -> dict:
    import requests
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        resp = requests.post(
            f"https://api.clickup.com/api/v2/task/{task_id}/comment",
            json={"comment_text": comment_text},
            headers={"Authorization": access_token, "Content-Type": "application/json"},
            timeout=30
        )
        if resp.status_code not in (200, 201):
            return {"success": False, "data": None, "error": f"Create comment failed: {resp.status_code} {resp.text}"}

        return {"success": True, "data": resp.json(), "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
