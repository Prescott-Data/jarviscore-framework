def reddit_get_subreddit(auth_info: dict, subreddit: str, limit: int = 10) -> dict:
    import requests
    # returns subreddit info and top hot posts
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "jarviscore/1.0"
        }

        # get subreddit about info
        about_resp = requests.get(
            f"https://oauth.reddit.com/r/{subreddit}/about",
            headers=headers,
            timeout=30
        )
        if about_resp.status_code != 200:
            return {"success": False, "data": None, "error": f"Get subreddit failed: {about_resp.status_code} {about_resp.text}"}

        # get hot posts
        posts_resp = requests.get(
            f"https://oauth.reddit.com/r/{subreddit}/hot",
            params={"limit": limit},
            headers=headers,
            timeout=30
        )
        posts = []
        if posts_resp.status_code == 200:
            posts = [p["data"] for p in posts_resp.json().get("data", {}).get("children", [])]

        about = about_resp.json().get("data", {})
        return {
            "success": True,
            "data": {
                "name": about.get("display_name"),
                "title": about.get("title"),
                "description": about.get("public_description"),
                "subscribers": about.get("subscribers"),
                "hot_posts": posts
            },
            "error": None
        }

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
