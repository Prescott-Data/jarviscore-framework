def mailchimp_get_list_members(auth_info: dict, list_id: str, count: int = 50, offset: int = 0, status: str = "subscribed") -> dict:
    import requests
    server = auth_info.get("server_prefix", "us1")
    _base = f"https://{server}.api.mailchimp.com/3.0"
    params = {"count": count, "offset": offset, "status": status}
    resp = requests.get(f"{_base}/lists/{list_id}/members", params=params, auth=("anystring", auth_info.get("api_key", "")), timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return {"success": True, "members": data.get("members", []), "total_items": data.get("total_items", 0)}
