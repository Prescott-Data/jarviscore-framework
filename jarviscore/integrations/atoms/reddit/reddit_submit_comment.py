def reddit_submit_comment(auth_info: dict, parent_id: str, text: str) -> dict:
    import requests
    # parent_id: fullname of post (t3_xxx) or comment (t1_xxx) to reply to
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        resp = requests.post(
            "https://oauth.reddit.com/api/comment",
            data={"parent": parent_id, "text": text},
            headers={
                "Authorization": f"Bearer {access_token}",
                "User-Agent": "collabra-integration-agent/1.0"
            },
            timeout=30
        )
        if resp.status_code != 200:
            return {"success": False, "data": None, "error": f"Submit comment failed: {resp.status_code} {resp.text}"}

        data = resp.json()
        comments = data.get("jquery", [])
        # extract comment data from response
        comment_data = None
        for item in data.get("jquery", []):
            if isinstance(item, list) and len(item) > 3 and isinstance(item[3], list):
                for sub in item[3]:
                    if isinstance(sub, dict) and sub.get("kind") == "t1":
                        comment_data = sub.get("data")
                        break

        return {"success": True, "data": comment_data or data, "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
