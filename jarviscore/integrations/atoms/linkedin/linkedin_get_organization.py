def linkedin_get_organization(auth_info: dict, organization_id: str) -> dict:
    import requests
    _base = "https://api.linkedin.com/v2"
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
    o = _get(f"/organizations/{organization_id}", params={
        "projection": "(id,name,vanityName,description,staffCountRange,industries,logoV2)"
    })
    name = o.get("name", {}).get("localized", {})
    desc = o.get("description", {}).get("localized", {})
    return {
        "id": o.get("id"),
        "name": next(iter(name.values()), None) if name else None,
        "vanity_name": o.get("vanityName"),
        "description": next(iter(desc.values()), None) if desc else None,
        "staff_count_range": o.get("staffCountRange"),
        "industries": o.get("industries", []),
        "profile_url": f"https://www.linkedin.com/company/{o.get('vanityName')}" if o.get("vanityName") else None
    }
