def notion_create_page(auth_info: dict, parent_id: str, title: str, parent_type: str = "page") -> dict:
    import requests
    # parent_type: "page" or "database"
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        if parent_type == "database":
            parent = {"database_id": parent_id}
        else:
            parent = {"page_id": parent_id}

        resp = requests.post(
            "https://api.notion.com/v1/pages",
            json={
                "parent": parent,
                "properties": {
                    "title": {
                        "title": [{"type": "text", "text": {"content": title}}]
                    }
                }
            },
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "Notion-Version": "2022-06-28"
            },
            timeout=30
        )
        if resp.status_code not in (200, 201):
            return {"success": False, "data": None, "error": f"Create page failed: {resp.status_code} {resp.text}"}

        return {"success": True, "data": resp.json(), "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
