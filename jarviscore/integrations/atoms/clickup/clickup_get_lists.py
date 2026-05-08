def clickup_get_lists(auth_info: dict, space_id: str) -> dict:
    import requests
    # returns folderless lists directly in the space
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        resp = requests.get(
            f"https://api.clickup.com/api/v2/space/{space_id}/list",
            headers={"Authorization": access_token},
            timeout=30
        )
        if resp.status_code != 200:
            return {"success": False, "data": None, "error": f"Get lists failed: {resp.status_code} {resp.text}"}

        lists = resp.json().get("lists", [])
        return {"success": True, "data": {"lists": lists, "count": len(lists)}, "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
