def linkedin_ads_list_campaign_groups(auth_info: dict, account_id: str, count: int = 25, start: int = 0) -> list:
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
    resp = _get("/adCampaignGroupsV2", params={
        "q": "search",
        "search.account.values": f"List({account_urn})",
        "count": count,
        "start": start
    })
    return [
        {
            "id": g.get("id"),
            "name": g.get("name"),
            "status": g.get("status"),
            "account": g.get("account"),
            "run_schedule_start": g.get("runSchedule", {}).get("start"),
            "run_schedule_end": g.get("runSchedule", {}).get("end"),
            "total_budget": g.get("totalBudget", {}).get("amount")
        }
        for g in resp.get("elements", [])
    ]
