def linkedin_ads_list_creatives(auth_info: dict, campaign_id: str, count: int = 25, start: int = 0) -> list:
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
    campaign_urn = f"urn:li:sponsoredCampaign:{campaign_id}"
    resp = _get("/adCreativesV2", params={
        "q": "search",
        "search.campaign.values": f"List({campaign_urn})",
        "count": count,
        "start": start
    })
    return [
        {
            "id": cr.get("id"),
            "status": cr.get("status"),
            "type": cr.get("type"),
            "campaign": cr.get("campaign"),
            "reference": cr.get("reference"),
            "variables": cr.get("variables")
        }
        for cr in resp.get("elements", [])
    ]
