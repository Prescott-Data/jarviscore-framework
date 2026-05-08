def notion_search(auth_info: dict, query: str, filter_type: str = None) -> dict:
    import requests
    # filter_type: "page" or "database" or None for both
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        payload = {"query": query}
        if filter_type in ("page", "database"):
            payload["filter"] = {"value": filter_type, "property": "object"}

        resp = requests.post(
            "https://api.notion.com/v1/search",
            json=payload,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "Notion-Version": "2022-06-28"
            },
            timeout=30
        )
        if resp.status_code != 200:
            return {"success": False, "data": None, "error": f"Search failed: {resp.status_code} {resp.text}"}

        results = resp.json().get("results", [])
        return {"success": True, "data": {"results": results, "count": len(results)}, "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
