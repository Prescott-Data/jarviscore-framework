def linkedin_ads_get_campaign(auth_info: dict, campaign_id: str) -> dict:
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
    c = _get(f"/adCampaignsV2/{campaign_id}")
    return {
        "id": c.get("id"),
        "name": c.get("name"),
        "status": c.get("status"),
        "type": c.get("type"),
        "objective_type": c.get("objectiveType"),
        "cost_type": c.get("costType"),
        "daily_budget": c.get("dailyBudget", {}).get("amount"),
        "unit_cost": c.get("unitCost", {}).get("amount"),
        "targeting_criteria": c.get("targetingCriteria"),
        "campaign_group": c.get("campaignGroup"),
        "account": c.get("account"),
        "run_schedule_start": c.get("runSchedule", {}).get("start"),
        "run_schedule_end": c.get("runSchedule", {}).get("end")
    }
