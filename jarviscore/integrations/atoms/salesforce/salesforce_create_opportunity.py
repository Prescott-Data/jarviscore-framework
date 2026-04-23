def salesforce_create_opportunity(auth_info: dict, name: str, stage: str, close_date: str, account_id: str = None, amount: float = None) -> dict:
    import requests
    instance = auth_info.get("instance_url", "").rstrip("/")
    _h = {"Authorization": f"Bearer {auth_info.get('access_token', '')}", "Content-Type": "application/json"}
    payload = {"Name": name, "StageName": stage, "CloseDate": close_date}
    if account_id: payload["AccountId"] = account_id
    if amount is not None: payload["Amount"] = amount
    resp = requests.post(f"{instance}/services/data/v58.0/sobjects/Opportunity", headers=_h, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return {"success": True, "id": data.get("id"), "name": name, "stage": stage}
