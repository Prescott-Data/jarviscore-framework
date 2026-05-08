def openmrs_list_observations(auth_info: dict, patient_uuid: str, concept_uuid: str = None, limit: int = 25) -> list:
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
    params = {"patient": patient_uuid, "limit": limit, "v": "default"}
    if concept_uuid:
        params["concept"] = concept_uuid
    resp = _get("/obs", params=params)
    return [
        {
            "uuid": o.get("uuid"),
            "concept": o.get("concept", {}).get("display"),
            "value": o.get("value") if not isinstance(o.get("value"), dict) else o.get("value", {}).get("display"),
            "datetime": o.get("obsDatetime"),
            "encounter": o.get("encounter", {}).get("display") if isinstance(o.get("encounter"), dict) else None
        }
        for o in resp.get("results", [])
    ]
