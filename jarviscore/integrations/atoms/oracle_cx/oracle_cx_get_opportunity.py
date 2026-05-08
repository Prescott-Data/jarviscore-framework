def oracle_cx_get_opportunity(auth_info: dict, instance_url: str, opportunity_id: str) -> dict:
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
    resp = _get(f"/opportunities/{opportunity_id}")
    return {
        "id": resp.get("OptyId"),
        "name": resp.get("Name"),
        "description": resp.get("Description"),
        "status": resp.get("StatusCode"),
        "sales_stage": resp.get("SalesStage"),
        "win_probability": resp.get("WinProb"),
        "revenue": resp.get("Revenue"),
        "currency": resp.get("CurrencyCode"),
        "close_date": resp.get("CloseDate"),
        "owner": resp.get("OwnerName"),
        "account": resp.get("TargetPartyName"),
        "created_at": resp.get("CreationDate"),
        "updated_at": resp.get("LastUpdateDate")
    }
