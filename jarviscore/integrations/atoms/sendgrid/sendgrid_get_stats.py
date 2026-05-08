def sendgrid_get_stats(auth_info: dict, start_date: str, end_date: str = None) -> dict:
    import requests
    _h = {"Authorization": f"Bearer {auth_info.get('api_key', '')}"}
    params = {"start_date": start_date, "aggregated_by": "day"}
    if end_date:
        params["end_date"] = end_date
    resp = requests.get("https://api.sendgrid.com/v3/stats", headers=_h, params=params, timeout=30)
    resp.raise_for_status()
    return {"success": True, "stats": resp.json()}
