def airtable_update_record(
    auth_info: dict,
    base_id: str,
    table_name: str,
    record_id: str,
    fields: dict
) -> dict:
    """Update specific fields on an existing Airtable record (partial update)."""
    import requests
    _base = "https://api.airtable.com/v0"
    _h = {"Authorization": f"Bearer {auth_info.get('access_token', '')}", "Content-Type": "application/json"}
    def _patch(p, data=None, headers=None):
        _r = requests.patch(f"{_base}{p}", headers={**_h, **(headers or {})}, json=data, timeout=30)
        _r.raise_for_status()
        return _r.json() if _r.content else {}

    return _patch(f"/{base_id}/{table_name}/{record_id}", {"fields": fields})
