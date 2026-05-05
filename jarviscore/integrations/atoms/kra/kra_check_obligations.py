def kra_check_obligations(auth_info: dict, krapin: str) -> dict:
    import requests
    base_url = auth_info.get("base_url", "https://sbx.kra.go.ke").rstrip("/")
    client_id = auth_info.get("client_id")
    client_secret = auth_info.get("client_secret")

    if not client_id or not client_secret:
        return {"success": False, "krapin": krapin, "data": None, "error": "auth_info must include client_id and client_secret"}

    try:
        # fetch bearer token using client credentials
        token_resp = requests.get(
            f"{base_url}/v1/token/generate",
            params={"grant_type": "client_credentials"},
            auth=(client_id, client_secret),
            timeout=30
        )
        if token_resp.status_code != 200:
            return {"success": False, "krapin": krapin, "data": None, "error": f"Token request failed: {token_resp.status_code} {token_resp.text}"}

        access_token = token_resp.json().get("access_token")
        if not access_token:
            return {"success": False, "krapin": krapin, "data": None, "error": "No access_token in token response"}

        # check tax obligations for the given KRA PIN
        resp = requests.post(
            f"{base_url}/dtd/checker/v1/obligation",
            json={"taxPayerPin": krapin},
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            timeout=30
        )
        if resp.status_code != 200:
            return {"success": False, "krapin": krapin, "data": None, "error": f"Obligations check failed: {resp.status_code} {resp.text}"}

        return {"success": True, "krapin": krapin, "data": resp.json(), "error": None}

    except Exception as e:
        return {"success": False, "krapin": krapin, "data": None, "error": str(e)}
