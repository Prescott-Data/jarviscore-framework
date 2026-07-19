def reddit_get_post(auth_info: dict, post_id: str) -> dict:
    import requests
    # post_id: the base36 ID e.g. "t3_abc123" or just "abc123"
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        # strip t3_ prefix if present
        clean_id = post_id.replace("t3_", "")
        resp = requests.get(
            f"https://oauth.reddit.com/api/info",
            params={"id": f"t3_{clean_id}"},
            headers={
                "Authorization": f"Bearer {access_token}",
                "User-Agent": "jarviscore/1.0"
            },
            timeout=30
        )
        if resp.status_code != 200:
            return {"success": False, "data": None, "error": f"Get post failed: {resp.status_code} {resp.text}"}

        children = resp.json().get("data", {}).get("children", [])
        if not children:
            return {"success": False, "data": None, "error": "Post not found"}

        return {"success": True, "data": children[0].get("data"), "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
