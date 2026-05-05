def netsuite_list_customers(auth_info: dict, account_id: str, limit: int = 25, offset: int = 0) -> list:
    import requests
    _base = f"https://{account_id}.suitetalk.api.netsuite.com/services/rest/record/v1"
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
    resp = _get(
        "/customer",
        params={"limit": limit, "offset": offset}
    )
    return [
        {
            "id": c.get("id"),
            "name": c.get("companyName"),
            "email": c.get("email"),
            "phone": c.get("phone"),
            "currency": c.get("currency", {}).get("refName") if isinstance(c.get("currency"), dict) else c.get("currency"),
            "status": c.get("entityStatus", {}).get("refName") if isinstance(c.get("entityStatus"), dict) else c.get("entityStatus"),
            "links": c.get("links", [])
        }
        for c in resp.get("items", [])
    ]
