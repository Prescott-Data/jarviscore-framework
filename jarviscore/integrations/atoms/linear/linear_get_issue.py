def linear_get_issue(auth_info: dict, issue_id: str) -> dict:
    import requests
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    query = """
    query($id: String!) {
        issue(id: $id) {
            id
            identifier
            title
            description
            priority
            state {
                name
            }
            assignee {
                name
                email
            }
            team {
                name
                key
            }
            labels {
                nodes {
                    name
                }
            }
            createdAt
            updatedAt
        }
    }
    """

    try:
        resp = requests.post(
            "https://api.linear.app/graphql",
            json={"query": query, "variables": {"id": issue_id}},
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            timeout=30
        )
        if resp.status_code != 200:
            return {"success": False, "data": None, "error": f"Get issue failed: {resp.status_code} {resp.text}"}

        data = resp.json()
        if "errors" in data:
            return {"success": False, "data": None, "error": str(data["errors"])}

        return {"success": True, "data": data["data"]["issue"], "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
