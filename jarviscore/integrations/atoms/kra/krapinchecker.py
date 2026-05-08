def kra_check_pin(auth_info: dict, taxpayer_id: str, taxpayer_type: str = "KE") -> dict:
    import requests
    base_url = auth_info.get("base_url", "https://sbx.kra.go.ke").rstrip("/")
    client_id = auth_info.get("client_id")
    client_secret = auth_info.get("client_secret")

    if not client_id or not client_secret:
        return {"success": False, "taxpayer_id": taxpayer_id, "data": None, "error": "auth_info must include client_id and client_secret"}

    try:
        # fetch bearer token using client credentials
        token_resp = requests.get(
            f"{base_url}/v1/token/generate",
            params={"grant_type": "client_credentials"},
            auth=(client_id, client_secret),
            timeout=30
        )
        if token_resp.status_code != 200:
            return {"success": False, "taxpayer_id": taxpayer_id, "data": None, "error": f"Token request failed: {token_resp.status_code} {token_resp.text}"}

        access_token = token_resp.json().get("access_token")
        if not access_token:
            return {"success": False, "taxpayer_id": taxpayer_id, "data": None, "error": "No access_token in token response"}

        # look up KRA PIN by national ID
        pin_resp = requests.post(
            f"{base_url}/checker/v1/pin",
            json={"TaxpayerType": taxpayer_type, "TaxpayerID": taxpayer_id},
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            timeout=30
        )
        if pin_resp.status_code != 200:
            return {"success": False, "taxpayer_id": taxpayer_id, "data": None, "error": f"PIN check failed: {pin_resp.status_code} {pin_resp.text}"}

        return {"success": True, "taxpayer_id": taxpayer_id, "data": pin_resp.json(), "error": None}

    except Exception as e:
        return {"success": False, "taxpayer_id": taxpayer_id, "data": None, "error": str(e)}
