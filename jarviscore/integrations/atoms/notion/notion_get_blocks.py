def notion_get_blocks(auth_info: dict, page_id: str) -> dict:
    import requests
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        blocks = []
        url = f"https://api.notion.com/v1/blocks/{page_id}/children"
        headers = {"Authorization": f"Bearer {access_token}", "Notion-Version": "2022-06-28"}

        while url:
            resp = requests.get(url, headers=headers, timeout=30)
            if resp.status_code != 200:
                return {"success": False, "data": None, "error": f"Get blocks failed: {resp.status_code} {resp.text}"}
            result = resp.json()
            blocks.extend(result.get("results", []))
            # paginate if more blocks exist
            url = None
            if result.get("has_more") and result.get("next_cursor"):
                url = f"https://api.notion.com/v1/blocks/{page_id}/children?start_cursor={result['next_cursor']}"

        return {"success": True, "data": {"blocks": blocks, "count": len(blocks)}, "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
