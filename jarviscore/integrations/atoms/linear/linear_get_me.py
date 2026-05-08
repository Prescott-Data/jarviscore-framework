def linear_get_me(auth_info: dict) -> dict:
    import requests
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    query = """
    query {
        viewer {
            id
            name
            email
            displayName
            avatarUrl
            createdAt
        }
    }
    """

    try:
        resp = requests.post(
            "https://api.linear.app/graphql",
            json={"query": query},
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            timeout=30
        )
        if resp.status_code != 200:
            return {"success": False, "data": None, "error": f"Get me failed: {resp.status_code} {resp.text}"}

        data = resp.json()
        if "errors" in data:
            return {"success": False, "data": None, "error": str(data["errors"])}

        return {"success": True, "data": data["data"]["viewer"], "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
