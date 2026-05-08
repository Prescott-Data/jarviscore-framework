def airtable_search_records(
    auth_info: dict,
    base_id: str,
    table_name: str,
    field_name: str,
    value: str
) -> list:
    """Search for records in an Airtable table where a specific field matches a value."""
    import requests
    _base = "https://api.airtable.com/v0"
    _h = {"Authorization": f"Bearer {auth_info.get('access_token', '')}", "Content-Type": "application/json"}
    def _get(p, params=None, headers=None):
        _r = requests.get(f"{_base}{p}", headers={**_h, **(headers or {})}, params=params or {}, timeout=30)
        _r.raise_for_status()
        return _r.json()

    filter_formula = f"{{{field_name}}}='{value}'"
    result = _get(f"/{base_id}/{table_name}", params={"filterByFormula": filter_formula})
    return result.get("records", [])
