def webex_search_people(auth_info: dict, email: str = None, display_name: str = None, max_results: int = 10) -> dict:
    import requests
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    if not email and not display_name:
        return {"success": False, "data": None, "error": "Either email or display_name must be provided"}

    try:
        params = {"max": max_results}
        if email:
            params["email"] = email
        if display_name:
            params["displayName"] = display_name

        resp = requests.get(
            "https://webexapis.com/v1/people",
            headers={"Authorization": f"Bearer {access_token}"},
            params=params,
            timeout=30
        )
        if resp.status_code != 200:
            return {"success": False, "data": None, "error": f"Search people failed: {resp.status_code} {resp.text}"}

        people = resp.json().get("items", [])
        return {"success": True, "data": {"people": people, "count": len(people)}, "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
