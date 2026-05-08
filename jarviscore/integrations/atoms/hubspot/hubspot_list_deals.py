def hubspot_list_deals(auth_info: dict, limit: int = 50, after: str = None) -> dict:
    import requests
    _h = {"Authorization": f"Bearer {auth_info.get('access_token', '')}"}
    params = {"limit": limit, "properties": "dealname,dealstage,amount,closedate,pipeline"}
    if after: params["after"] = after
    resp = requests.get("https://api.hubapi.com/crm/v3/objects/deals", headers=_h, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return {"success": True, "deals": data.get("results", []), "paging": data.get("paging")}
