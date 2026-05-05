def linkedin_get_profile(auth_info: dict) -> dict:
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
    p = _get("/me", params={
        "projection": "(id,firstName,lastName,headline,vanityName,profilePicture(displayImage~:playableStreams))"
    })
    first = p.get("firstName", {}).get("localized", {})
    last = p.get("lastName", {}).get("localized", {})
    first_name = next(iter(first.values()), None) if first else None
    last_name = next(iter(last.values()), None) if last else None
    return {
        "id": p.get("id"),
        "first_name": first_name,
        "last_name": last_name,
        "headline": next(iter(p.get("headline", {}).get("localized", {}).values()), None),
        "vanity_name": p.get("vanityName"),
        "profile_url": f"https://www.linkedin.com/in/{p.get('vanityName')}" if p.get("vanityName") else None
    }
