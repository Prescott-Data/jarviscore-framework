def sap_get_business_partner(auth_info: dict, account_id: str, partner_id: str) -> dict:
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
    resp = _get(
        f"/sap/opu/odata/sap/API_BUSINESS_PARTNER/A_BusinessPartner('{partner_id}')",
        params={"$format": "json"},
        headers={"Accept": "application/json"}
    )
    p = resp.get("d", {})
    return {
        "id": p.get("BusinessPartner"),
        "name": p.get("BusinessPartnerFullName"),
        "first_name": p.get("FirstName"),
        "last_name": p.get("LastName"),
        "category": p.get("BusinessPartnerCategory"),
        "type": p.get("BusinessPartnerType"),
        "group": p.get("BusinessPartnerGrouping"),
        "language": p.get("Language"),
        "created_at": p.get("CreationDate"),
        "changed_at": p.get("LastChangeDate")
    }
