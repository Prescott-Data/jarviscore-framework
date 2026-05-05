def _get_twitter_user_id(access_token: str) -> str:
    resp = requests.get(
        "https://api.twitter.com/2/users/me",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30
    )
    resp.raise_for_status()
    return resp.json()["data"]["id"]

def twitter_like_tweet(auth_info: dict, tweet_id: str) -> dict:
    import requests
    try:
        access_token = _get_nexus_token(auth_info)
        twitter_user_id = _get_twitter_user_id(access_token)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        resp = requests.post(
            f"https://api.twitter.com/2/users/{twitter_user_id}/likes",
            json={"tweet_id": tweet_id},
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            timeout=30
        )
        if resp.status_code not in (200, 201):
            return {"success": False, "data": None, "error": f"Like tweet failed: {resp.status_code} {resp.text}"}

        return {"success": True, "data": resp.json().get("data"), "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
