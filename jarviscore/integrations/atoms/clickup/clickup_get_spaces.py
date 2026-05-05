def _get_workspace_id(access_token: str, auth_info: dict) -> str:
    if auth_info.get("workspace_id"):
        return auth_info["workspace_id"]
    resp = requests.get(
        "https://api.clickup.com/api/v2/team",
        headers={"Authorization": access_token},
        timeout=30
    )
    resp.raise_for_status()
    teams = resp.json().get("teams", [])
    if not teams:
        raise RuntimeError("No ClickUp workspaces found for this account")
    return teams[0]["id"]

def clickup_get_spaces(auth_info: dict) -> dict:
    import requests
    try:
        access_token = _get_nexus_token(auth_info)
        workspace_id = _get_workspace_id(access_token, auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        resp = requests.get(
            f"https://api.clickup.com/api/v2/team/{workspace_id}/space",
            headers={"Authorization": access_token},
            timeout=30
        )
        if resp.status_code != 200:
            return {"success": False, "data": None, "error": f"Get spaces failed: {resp.status_code} {resp.text}"}

        spaces = resp.json().get("spaces", [])
        return {"success": True, "data": {"spaces": spaces, "count": len(spaces)}, "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
