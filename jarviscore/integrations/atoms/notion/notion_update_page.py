def notion_update_page(auth_info: dict, page_id: str, title: str = None, archived: bool = None) -> dict:
    import requests
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        payload = {}
        if title is not None:
            payload["properties"] = {
                "title": {
                    "title": [{"type": "text", "text": {"content": title}}]
                }
            }
        if archived is not None:
            payload["archived"] = archived

        resp = requests.patch(
            f"https://api.notion.com/v1/pages/{page_id}",
            json=payload,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "Notion-Version": "2022-06-28"
            },
            timeout=30
        )
        if resp.status_code != 200:
            return {"success": False, "data": None, "error": f"Update page failed: {resp.status_code} {resp.text}"}

        return {"success": True, "data": resp.json(), "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
