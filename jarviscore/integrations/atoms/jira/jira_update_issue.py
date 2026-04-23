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

def jira_update_issue(auth_info: dict, issue_key: str, fields: dict) -> dict:
    import requests
    domain = auth_info.get("domain", "").rstrip("/")
    if not domain:
        return {"success": False, "issue_key": issue_key, "data": None, "error": "auth_info must include domain (e.g. your-domain.atlassian.net)"}

    try:
        access_token = _get_nexus_token(auth_info)
        cloud_id = _get_cloud_id(access_token, auth_info)
    except Exception as e:
        return {"success": False, "issue_key": issue_key, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        resp = requests.put(
            f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/issue/{issue_key}",
            json={"fields": fields},
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            timeout=30
        )
        # Jira returns 204 No Content on successful update
        if resp.status_code not in (200, 204):
            return {"success": False, "issue_key": issue_key, "data": None, "error": f"Update issue failed: {resp.status_code} {resp.text}"}

        return {"success": True, "issue_key": issue_key, "data": {"updated": True}, "error": None}

    except Exception as e:
        return {"success": False, "issue_key": issue_key, "data": None, "error": str(e)}
