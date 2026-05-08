def gmail_list_messages(auth_info: dict, query: str = "", max_results: int = 20) -> dict:
    import requests
    _base = "https://gmail.googleapis.com/gmail/v1/users/me"
    _h = {"Authorization": f"Bearer {auth_info.get('access_token', '')}"}
    params = {"maxResults": max_results}
    if query:
        params["q"] = query
    resp = requests.get(f"{_base}/messages", headers=_h, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return {"success": True, "messages": data.get("messages", []), "result_size_estimate": data.get("resultSizeEstimate", 0)}
