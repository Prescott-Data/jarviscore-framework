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

def freshbooks_record_payment(auth_info: dict, invoice_id: str, amount: str, date: str, payment_type: str = "Check", notes: str = None) -> dict:
    import requests
    # date format: "2026-03-24", payment_type: "Check", "Credit", "Cash", etc.
    try:
        access_token = _get_nexus_token(auth_info)
        account_id = _get_account_id(access_token, auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        payment = {
            "invoiceid": invoice_id,
            "amount": {"amount": amount},
            "date": date,
            "type": payment_type
        }
        if notes:
            payment["notes"] = notes

        resp = requests.post(
            f"https://api.freshbooks.com/accounting/account/{account_id}/payments/payments",
            json={"payment": payment},
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            timeout=30
        )
        if resp.status_code not in (200, 201):
            return {"success": False, "data": None, "error": f"Record payment failed: {resp.status_code} {resp.text}"}

        return {"success": True, "data": resp.json().get("response", {}).get("result", {}).get("payment"), "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
