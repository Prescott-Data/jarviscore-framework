def linear_search_issues(auth_info: dict, query: str, max_results: int = 20) -> dict:
    import requests
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    gql = """
    query($term: String!, $first: Int!) {
        issues(filter: { title: { containsIgnoreCase: $term } }, first: $first) {
            nodes {
                id
                identifier
                title
                priority
                state {
                    name
                }
                assignee {
                    name
                }
                team {
                    name
                    key
                }
                createdAt
            }
        }
    }
    """

    try:
        resp = requests.post(
            "https://api.linear.app/graphql",
            json={"query": gql, "variables": {"term": query, "first": max_results}},
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            timeout=30
        )
        if resp.status_code != 200:
            return {"success": False, "data": None, "error": f"Search issues failed: {resp.status_code} {resp.text}"}

        data = resp.json()
        if "errors" in data:
            return {"success": False, "data": None, "error": str(data["errors"])}

        issues = data["data"]["issues"]["nodes"]
        return {"success": True, "data": {"issues": issues, "count": len(issues)}, "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
