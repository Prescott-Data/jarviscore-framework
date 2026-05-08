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

def confluence_update_page(auth_info: dict, page_id: str, title: str, body: str, version: int) -> dict:
    import requests
    domain = auth_info.get("domain", "").rstrip("/")
    if not domain:
        return {"success": False, "page_id": page_id, "data": None, "error": "auth_info must include domain (e.g. prescott-data.atlassian.net)"}

    try:
        access_token = _get_nexus_token(auth_info)
        cloud_id = _get_cloud_id(access_token, auth_info)
    except Exception as e:
        return {"success": False, "page_id": page_id, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        payload = {
            "type": "page",
            "title": title,
            "version": {"number": version},
            "body": {
                "storage": {
                    "value": body,
                    "representation": "storage"
                }
            }
        }
        resp = requests.put(
            f"https://api.atlassian.com/ex/confluence/{cloud_id}/wiki/rest/api/content/{page_id}",
            json=payload,
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            timeout=30
        )
        if resp.status_code != 200:
            return {"success": False, "page_id": page_id, "data": None, "error": f"Update page failed: {resp.status_code} {resp.text}"}

        return {"success": True, "page_id": page_id, "data": resp.json(), "error": None}

    except Exception as e:
        return {"success": False, "page_id": page_id, "data": None, "error": str(e)}
