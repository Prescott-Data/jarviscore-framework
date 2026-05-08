def reddit_vote(auth_info: dict, fullname: str, direction: int) -> dict:
    import requests
    # fullname: e.g. "t3_abc123" (post) or "t1_abc123" (comment)
    # direction: 1=upvote, -1=downvote, 0=remove vote
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        resp = requests.post(
            "https://oauth.reddit.com/api/vote",
            data={"id": fullname, "dir": direction},
            headers={
                "Authorization": f"Bearer {access_token}",
                "User-Agent": "collabra-integration-agent/1.0"
            },
            timeout=30
        )
        if resp.status_code != 200:
            return {"success": False, "data": None, "error": f"Vote failed: {resp.status_code} {resp.text}"}

        return {"success": True, "data": {"fullname": fullname, "direction": direction}, "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
