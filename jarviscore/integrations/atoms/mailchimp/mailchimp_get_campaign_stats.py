def mailchimp_get_campaign_stats(auth_info: dict, campaign_id: str) -> dict:
    import requests
    server = auth_info.get("server_prefix", "us1")
    _base = f"https://{server}.api.mailchimp.com/3.0"
    resp = requests.get(f"{_base}/reports/{campaign_id}", auth=("anystring", auth_info.get("api_key", "")), timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return {"success": True, "campaign_id": campaign_id, "emails_sent": data.get("emails_sent"), "opens": data.get("opens", {}).get("unique_opens"), "clicks": data.get("clicks", {}).get("unique_clicks"), "unsubscribes": data.get("unsubscribes")}
