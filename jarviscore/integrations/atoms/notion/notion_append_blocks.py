def notion_append_blocks(auth_info: dict, page_id: str, blocks: list) -> dict:
    import requests
    # blocks: list of Notion block objects
    # e.g. [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": "Hello"}}]}}]
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        resp = requests.patch(
            f"https://api.notion.com/v1/blocks/{page_id}/children",
            json={"children": blocks},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "Notion-Version": "2022-06-28"
            },
            timeout=30
        )
        if resp.status_code != 200:
            return {"success": False, "data": None, "error": f"Append blocks failed: {resp.status_code} {resp.text}"}

        return {"success": True, "data": resp.json(), "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
