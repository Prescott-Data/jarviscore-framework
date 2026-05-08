def openmrs_get_patient(auth_info: dict, patient_uuid: str) -> dict:
    import requests
    _base = "https://o2.openmrs.org/openmrs/ws/rest/v1"
    _h = {"Authorization": f"Bearer {auth_info.get('access_token', '')}", "Content-Type": "application/json"}
    def _get(p, params=None, headers=None):
        _r = requests.get(f"{_base}{p}", headers={**_h, **(headers or {})}, params=params or {}, timeout=30)
        _r.raise_for_status()
        return _r.json()
    def _post(p, data=None, headers=None):
        _r = requests.post(f"{_base}{p}", headers={**_h, **(headers or {})}, json=data, timeout=30)
        _r.raise_for_status()
        return _r.json()
    def _put(p, data=None, headers=None):
        _r = requests.put(f"{_base}{p}", headers={**_h, **(headers or {})}, json=data, timeout=30)
        _r.raise_for_status()
        return _r.json()
    def _patch(p, data=None, headers=None):
        _r = requests.patch(f"{_base}{p}", headers={**_h, **(headers or {})}, json=data, timeout=30)
        _r.raise_for_status()
        return _r.json() if _r.content else {}
    def _delete(p, headers=None):
        _r = requests.delete(f"{_base}{p}", headers={**_h, **(headers or {})}, timeout=30)
        _r.raise_for_status()
        return _r.json() if _r.content else {}
    p = _get(f"/patient/{patient_uuid}", params={"v": "full"})
    person = p.get("person", {})
    names = person.get("names", [])
    preferred_name = next((n for n in names if n.get("preferred")), names[0] if names else {})
    return {
        "uuid": p.get("uuid"),
        "given_name": preferred_name.get("givenName"),
        "family_name": preferred_name.get("familyName"),
        "gender": person.get("gender"),
        "age": person.get("age"),
        "birthdate": person.get("birthdate"),
        "dead": person.get("dead", False),
        "death_date": person.get("deathDate"),
        "identifiers": [
            {"id": i.get("identifier"), "type": i.get("identifierType", {}).get("display"), "preferred": i.get("preferred")}
            for i in p.get("identifiers", [])
        ],
        "addresses": [
            {"address1": a.get("address1"), "city": a.get("cityVillage"), "country": a.get("country")}
            for a in person.get("addresses", [])
        ]
    }
