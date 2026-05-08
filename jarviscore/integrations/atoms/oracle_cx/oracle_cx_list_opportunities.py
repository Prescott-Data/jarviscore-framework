def oracle_cx_list_opportunities(auth_info: dict, instance_url: str, limit: int = 25, offset: int = 0) -> list:
    import requests
    _base = f"{instance_url.rstrip('/')}/crmRestApi/resources/latest"
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
    resp = _get("/opportunities", params={"limit": limit, "offset": offset})
    return [
        {
            "id": o.get("OptyId"),
            "name": o.get("Name"),
            "status": o.get("StatusCode"),
            "sales_stage": o.get("SalesStage"),
            "win_probability": o.get("WinProb"),
            "revenue": o.get("Revenue"),
            "currency": o.get("CurrencyCode"),
            "close_date": o.get("TargetWinProb"),
            "owner": o.get("OwnerName"),
            "account": o.get("TargetPartyName")
        }
        for o in resp.get("items", [])
    ]
