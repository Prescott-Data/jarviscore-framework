def apollo_get_person(auth_info: dict, person_id: str) -> dict:
    import requests
    _h = {"Content-Type": "application/json"}
    payload = {"api_key": auth_info.get("api_key", ""), "id": person_id}
    resp = requests.post("https://api.apollo.io/v1/people/match", headers=_h, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    person = data.get("person", {})
    return {"success": True, "id": person.get("id"), "name": person.get("name"), "title": person.get("title"), "email": person.get("email"), "organization": person.get("organization", {}).get("name"), "linkedin_url": person.get("linkedin_url")}
