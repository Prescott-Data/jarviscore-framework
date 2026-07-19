def reddit_submit_post(auth_info: dict, subreddit: str, title: str, text: str = None, url: str = None) -> dict:
    import requests
    # kind: "self" for text post, "link" for URL post
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        if url:
            kind = "link"
        else:
            kind = "self"

        payload = {
            "sr": subreddit,
            "title": title,
            "kind": kind,
            "resubmit": True,
            "nsfw": False,
            "spoiler": False
        }
        if text:
            payload["text"] = text
        if url:
            payload["url"] = url

        resp = requests.post(
            "https://oauth.reddit.com/api/submit",
            data=payload,
            headers={
                "Authorization": f"Bearer {access_token}",
                "User-Agent": "jarviscore/1.0"
            },
            timeout=30
        )
        if resp.status_code != 200:
            return {"success": False, "data": None, "error": f"Submit post failed: {resp.status_code} {resp.text}"}

        data = resp.json()
        jquery = data.get("jquery", [])
        # extract post URL from jquery response
        post_url = None
        for item in jquery:
            if isinstance(item, list) and len(item) > 3:
                if isinstance(item[3], list) and item[3] and isinstance(item[3][0], str):
                    from urllib.parse import urlparse
                    candidate = item[3][0]
                    try:
                        parsed = urlparse(candidate)
                        host = parsed.hostname or ""
                        if host == "reddit.com" or host.endswith(".reddit.com"):
                            post_url = candidate
                            break
                    except Exception:
                        pass

        return {"success": True, "data": {"post_url": post_url, "raw": data}, "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
