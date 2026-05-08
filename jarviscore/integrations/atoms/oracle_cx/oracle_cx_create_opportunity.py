def oracle_cx_create_opportunity(auth_info: dict, instance_url: str, name: str, account_party_id: str = None, revenue: float = None, close_date: str = None, sales_stage: str = None) -> dict:
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
    payload = {"Name": name}
    if account_party_id:
        payload["TargetPartyId"] = account_party_id
    if revenue is not None:
        payload["Revenue"] = revenue
    if close_date:
        payload["CloseDate"] = close_date
    if sales_stage:
        payload["SalesStage"] = sales_stage
    resp = _post("/opportunities", data=payload)
    return {
        "id": resp.get("OptyId"),
        "name": resp.get("Name"),
        "status": resp.get("StatusCode"),
        "sales_stage": resp.get("SalesStage"),
        "created_at": resp.get("CreationDate")
    }
