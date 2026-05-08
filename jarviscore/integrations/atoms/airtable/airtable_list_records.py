def airtable_list_records(
    auth_info: dict,
    base_id: str,
    table_name: str,
    filter_formula: str = None,
    max_records: int = None,
    view: str = None
) -> list:
    """List records from an Airtable table."""
    import requests
    _base = "https://api.airtable.com/v0"
    _h = {"Authorization": f"Bearer {auth_info.get('access_token', '')}", "Content-Type": "application/json"}
    def _get(p, params=None, headers=None):
        _r = requests.get(f"{_base}{p}", headers={**_h, **(headers or {})}, params=params or {}, timeout=30)
        _r.raise_for_status()
        return _r.json()

    params = {}
    if filter_formula:
        params["filterByFormula"] = filter_formula
    if max_records:
        params["maxRecords"] = max_records
    if view:
        params["view"] = view

    all_records = []
    offset = None

    while True:
        if offset:
            params["offset"] = offset
        result = _get(f"/{base_id}/{table_name}", params=params)
        all_records.extend(result.get("records", []))
        offset = result.get("offset")
        if not offset:
            break

    return all_records
