def airtable_create_record(auth_info: dict, base_id: str, table_name: str, fields: dict) -> dict:
    import requests
    _base = "https://api.airtable.com/v0"
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
    """
    Create a new record in an Airtable table.

    Args:
        auth_info: Dict with access_token for the tool
        base_id:       Airtable base ID (e.g. appXXXXXXXXXXXXXX)
        table_name:    Table name or table ID
        fields:        Dict of field names to values (e.g. {"Name": "Acme Corp", "Status": "Active"})

    Returns:
        The created record including its assigned record ID.
    """
    return _post(f"/{base_id}/{table_name}", {"fields": fields})
