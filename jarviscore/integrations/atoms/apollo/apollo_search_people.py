def apollo_search_people(auth_info: dict, job_titles: list = None, locations: list = None, organization_domains: list = None, page: int = 1, per_page: int = 25) -> dict:
    import requests
    _h = {"Content-Type": "application/json", "Cache-Control": "no-cache"}
    payload = {"api_key": auth_info.get("api_key", ""), "page": page, "per_page": per_page}
    if job_titles: payload["person_titles"] = job_titles
    if locations: payload["person_locations"] = locations
    if organization_domains: payload["organization_domains"] = organization_domains
    resp = requests.post("https://api.apollo.io/v1/mixed_people/search", headers=_h, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return {"success": True, "people": data.get("people", []), "total_entries": data.get("pagination", {}).get("total_entries", 0), "page": page}
