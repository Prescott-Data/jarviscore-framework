def linear_get_issues(auth_info: dict, team_id: str = None, max_results: int = 50) -> dict:
    import requests
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    filter_clause = f'filter: {{ team: {{ id: {{ eq: "{team_id}" }} }} }},' if team_id else ""

    query = f"""
    query {{
        issues({filter_clause} first: {max_results}) {{
            nodes {{
                id
                identifier
                title
                description
                priority
                state {{
                    name
                }}
                assignee {{
                    name
                }}
                createdAt
                updatedAt
            }}
        }}
    }}
    """

    try:
        resp = requests.post(
            "https://api.linear.app/graphql",
            json={"query": query},
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            timeout=30
        )
        if resp.status_code != 200:
            return {"success": False, "data": None, "error": f"Get issues failed: {resp.status_code} {resp.text}"}

        data = resp.json()
        if "errors" in data:
            return {"success": False, "data": None, "error": str(data["errors"])}

        issues = data["data"]["issues"]["nodes"]
        return {"success": True, "data": {"issues": issues, "count": len(issues)}, "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
