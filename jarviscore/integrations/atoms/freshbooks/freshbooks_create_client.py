def _get_account_id(access_token: str, auth_info: dict) -> str:
    if auth_info.get("account_id"):
        return auth_info["account_id"]
    resp = requests.get(
        "https://api.freshbooks.com/auth/api/v1/users/me",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        timeout=30
    )
    resp.raise_for_status()
    memberships = resp.json().get("response", {}).get("business_memberships", [])
    if not memberships:
        raise RuntimeError("No business memberships found on FreshBooks account")
    return memberships[0]["business"]["account_id"]

def freshbooks_create_client(auth_info: dict, email: str, organization: str = None, first_name: str = None, last_name: str = None, phone: str = None) -> dict:
    import requests
    try:
        access_token = _get_nexus_token(auth_info)
        account_id = _get_account_id(access_token, auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        client = {"email": email}
        if organization:
            client["organization"] = organization
        if first_name:
            client["fname"] = first_name
        if last_name:
            client["lname"] = last_name
        if phone:
            client["mob_phone"] = phone

        resp = requests.post(
            f"https://api.freshbooks.com/accounting/account/{account_id}/users/clients",
            json={"client": client},
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            timeout=30
        )
        if resp.status_code not in (200, 201):
            return {"success": False, "data": None, "error": f"Create client failed: {resp.status_code} {resp.text}"}

        return {"success": True, "data": resp.json().get("response", {}).get("result", {}).get("client"), "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
