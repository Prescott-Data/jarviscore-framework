def _get_cloud_id(access_token: str, auth_info: dict) -> str:
    if auth_info.get("cloud_id"):
        return auth_info["cloud_id"]
    resp = requests.get(
        "https://api.atlassian.com/oauth/token/accessible-resources",
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        timeout=30
    )
    resp.raise_for_status()
    resources = resp.json()
    domain = auth_info.get("domain", "").rstrip("/")
    for r in resources:
        if domain and domain in r.get("url", ""):
            return r["id"]
    return resources[0]["id"]

def jira_create_issue(auth_info: dict, project_key: str, summary: str, issue_type: str = "Task", description: str = None) -> dict:
    import requests
    domain = auth_info.get("domain", "").rstrip("/")
    if not domain:
        return {"success": False, "data": None, "error": "auth_info must include domain (e.g. prescott-data.atlassian.net)"}

    try:
        access_token = _get_nexus_token(auth_info)
        cloud_id = _get_cloud_id(access_token, auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        payload = {
            "fields": {
                "project": {"key": project_key},
                "summary": summary,
                "issuetype": {"name": issue_type}
            }
        }
        if description:
            payload["fields"]["description"] = {
                "type": "doc",
                "version": 1,
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": description}]}]
            }

        resp = requests.post(
            f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/issue",
            json=payload,
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            timeout=30
        )
        if resp.status_code not in (200, 201):
            return {"success": False, "data": None, "error": f"Create issue failed: {resp.status_code} {resp.text}"}

        return {"success": True, "data": resp.json(), "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
