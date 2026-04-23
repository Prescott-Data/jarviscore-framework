def salesforce_soql_query(auth_info: dict, query: str) -> dict:
    import requests, urllib.parse
    instance = auth_info.get("instance_url", "").rstrip("/")
    _h = {"Authorization": f"Bearer {auth_info.get('access_token', '')}"}
    resp = requests.get(f"{instance}/services/data/v58.0/query", headers=_h, params={"q": query}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return {"success": True, "total_size": data.get("totalSize"), "done": data.get("done"), "records": data.get("records", [])}
