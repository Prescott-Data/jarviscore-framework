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

def freshbooks_create_expense(auth_info: dict, amount: str, currency_code: str, date: str, staff_id: str, category_id: str, notes: str = None, client_id: str = None) -> dict:
    import requests
    # date format: "2026-03-24", staff_id required by FreshBooks API
    try:
        access_token = _get_nexus_token(auth_info)
        account_id = _get_account_id(access_token, auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        expense = {
            "amount": {"amount": amount, "code": currency_code},
            "date": date,
            "staffid": staff_id
        }
        if notes:
            expense["notes"] = notes
        if client_id:
            expense["clientid"] = client_id
        expense["categoryid"] = category_id

        resp = requests.post(
            f"https://api.freshbooks.com/accounting/account/{account_id}/expenses/expenses",
            json={"expense": expense},
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            timeout=30
        )
        if resp.status_code not in (200, 201):
            return {"success": False, "data": None, "error": f"Create expense failed: {resp.status_code} {resp.text}"}

        return {"success": True, "data": resp.json().get("response", {}).get("result", {}).get("expense"), "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
