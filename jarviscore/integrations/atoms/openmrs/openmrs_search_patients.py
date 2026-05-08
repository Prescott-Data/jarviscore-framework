def openmrs_search_patients(auth_info: dict, query: str, limit: int = 25) -> list:
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
    resp = _get("/patient", params={"q": query, "limit": limit, "v": "default"})
    return [
        {
            "uuid": p.get("uuid"),
            "display": p.get("display"),
            "identifiers": [
                {"id": i.get("identifier"), "type": i.get("identifierType", {}).get("display")}
                for i in p.get("identifiers", [])
            ],
            "gender": p.get("person", {}).get("gender"),
            "age": p.get("person", {}).get("age"),
            "birthdate": p.get("person", {}).get("birthdate"),
            "dead": p.get("person", {}).get("dead", False)
        }
        for p in resp.get("results", [])
    ]
