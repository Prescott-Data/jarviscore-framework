def sap_list_business_partners(auth_info: dict, account_id: str, top: int = 25, filter: str = None) -> list:
    import requests
    _base = f"https://{account_id}.s4hana.ondemand.com"
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
    params = {"$top": top, "$format": "json"}
    if filter:
        params["$filter"] = filter
    resp = _get(
        "/sap/opu/odata/sap/API_BUSINESS_PARTNER/A_BusinessPartner",
        params=params,
        headers={"Accept": "application/json"}
    )
    results = resp.get("d", {}).get("results", [])
    return [
        {
            "id": p.get("BusinessPartner"),
            "name": p.get("BusinessPartnerFullName"),
            "category": p.get("BusinessPartnerCategory"),
            "type": p.get("BusinessPartnerType"),
            "group": p.get("BusinessPartnerGrouping"),
            "created_at": p.get("CreationDate")
        }
        for p in results
    ]
