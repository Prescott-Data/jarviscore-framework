def twitter_post_tweet(auth_info: dict, text: str) -> dict:
    import requests
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        resp = requests.post(
            "https://api.twitter.com/2/tweets",
            json={"text": text},
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            timeout=30
        )
        if resp.status_code not in (200, 201):
            return {"success": False, "data": None, "error": f"Post tweet failed: {resp.status_code} {resp.text}"}

        return {"success": True, "data": resp.json().get("data"), "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
