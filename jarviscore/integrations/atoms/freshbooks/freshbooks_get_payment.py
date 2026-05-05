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

def freshbooks_get_payment(auth_info: dict, payment_id: str) -> dict:
    import requests
    try:
        access_token = _get_nexus_token(auth_info)
        account_id = _get_account_id(access_token, auth_info)
    except Exception as e:
        return {"success": False, "payment_id": payment_id, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        resp = requests.get(
            f"https://api.freshbooks.com/accounting/account/{account_id}/payments/payments/{payment_id}",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            timeout=30
        )
        if resp.status_code != 200:
            return {"success": False, "payment_id": payment_id, "data": None, "error": f"Get payment failed: {resp.status_code} {resp.text}"}

        return {"success": True, "payment_id": payment_id, "data": resp.json().get("response", {}).get("result", {}).get("payment"), "error": None}

    except Exception as e:
        return {"success": False, "payment_id": payment_id, "data": None, "error": str(e)}
