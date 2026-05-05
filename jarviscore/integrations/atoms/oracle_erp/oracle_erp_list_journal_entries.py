def oracle_erp_list_journal_entries(auth_info: dict, instance_url: str, limit: int = 25, offset: int = 0) -> list:
    import requests
    _base = f"{instance_url.rstrip('/')}/fscmRestApi/resources/latest"
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
    resp = _get("/journalEntries", params={"limit": limit, "offset": offset})
    return [
        {
            "id": j.get("HeaderId"),
            "name": j.get("JournalName"),
            "batch_name": j.get("JournalBatchName"),
            "status": j.get("Status"),
            "currency": j.get("Currency"),
            "period": j.get("AccountingPeriod"),
            "ledger": j.get("LedgerName"),
            "description": j.get("Description"),
            "created_by": j.get("CreatedBy"),
            "created_at": j.get("CreationDate")
        }
        for j in resp.get("items", [])
    ]
