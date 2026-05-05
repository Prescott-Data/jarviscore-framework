def openmrs_list_encounters(auth_info: dict, patient_uuid: str, limit: int = 25) -> list:
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
    resp = _get("/encounter", params={"patient": patient_uuid, "limit": limit, "v": "default"})
    return [
        {
            "uuid": e.get("uuid"),
            "display": e.get("display"),
            "type": e.get("encounterType", {}).get("display"),
            "datetime": e.get("encounterDatetime"),
            "location": e.get("location", {}).get("display"),
            "provider": e.get("encounterProviders", [{}])[0].get("provider", {}).get("display") if e.get("encounterProviders") else None
        }
        for e in resp.get("results", [])
    ]
