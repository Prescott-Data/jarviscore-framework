def reddit_get_me(auth_info: dict) -> dict:
    import requests
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        resp = requests.get(
            "https://oauth.reddit.com/api/v1/me",
            headers={
                "Authorization": f"Bearer {access_token}",
                "User-Agent": "jarviscore/1.0"
            },
            timeout=30
        )
        if resp.status_code != 200:
            return {"success": False, "data": None, "error": f"Get me failed: {resp.status_code} {resp.text}"}

        data = resp.json()
        return {
            "success": True,
            "data": {
                "id": data.get("id"),
                "name": data.get("name"),
                "icon_img": data.get("icon_img"),
                "total_karma": data.get("total_karma"),
                "comment_karma": data.get("comment_karma"),
                "link_karma": data.get("link_karma"),
                "created_utc": data.get("created_utc")
            },
            "error": None
        }

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
