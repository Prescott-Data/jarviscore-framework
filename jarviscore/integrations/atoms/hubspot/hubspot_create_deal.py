def hubspot_create_deal(auth_info: dict, deal_name: str, stage: str, amount: float = None, pipeline: str = "default", close_date: str = None) -> dict:
    import requests
    _h = {"Authorization": f"Bearer {auth_info.get('access_token', '')}", "Content-Type": "application/json"}
    props = {"dealname": deal_name, "dealstage": stage, "pipeline": pipeline}
    if amount is not None: props["amount"] = str(amount)
    if close_date: props["closedate"] = close_date
    resp = requests.post("https://api.hubapi.com/crm/v3/objects/deals", headers=_h, json={"properties": props}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return {"success": True, "id": data.get("id"), "deal_name": deal_name, "stage": stage}
