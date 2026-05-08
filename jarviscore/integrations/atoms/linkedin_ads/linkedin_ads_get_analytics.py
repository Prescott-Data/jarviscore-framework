def linkedin_ads_get_analytics(auth_info: dict, account_id: str, start_year: int, start_month: int, start_day: int, end_year: int, end_month: int, end_day: int, pivot: str = "CAMPAIGN") -> list:
    import requests
    _base = "https://api.linkedin.com/v2"
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
    account_urn = f"urn:li:sponsoredAccount:{account_id}"
    resp = _get("/adAnalyticsV2", params={
        "q": "analytics",
        "pivot": pivot,
        "dateRange.start.year": start_year,
        "dateRange.start.month": start_month,
        "dateRange.start.day": start_day,
        "dateRange.end.year": end_year,
        "dateRange.end.month": end_month,
        "dateRange.end.day": end_day,
        "accounts": f"List({account_urn})",
        "fields": "impressions,clicks,costInLocalCurrency,totalEngagements,pivotValue"
    })
    return [
        {
            "pivot_value": r.get("pivotValue"),
            "impressions": r.get("impressions"),
            "clicks": r.get("clicks"),
            "cost": r.get("costInLocalCurrency"),
            "total_engagements": r.get("totalEngagements"),
            "date_range": r.get("dateRange")
        }
        for r in resp.get("elements", [])
    ]
