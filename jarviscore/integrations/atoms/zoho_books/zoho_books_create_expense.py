def zoho_books_create_expense(auth_info: dict, org_id: str, account_id: str, amount: float, date: str, paid_through_account_id: str, description: str = None, customer_id: str = None) -> dict:
    import requests
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        payload = {
            "account_id": account_id,
            "amount": amount,
            "date": date,
            "paid_through_account_id": paid_through_account_id
        }
        if description:
            payload["description"] = description
        if customer_id:
            payload["customer_id"] = customer_id

        resp = requests.post(
            "https://www.zohoapis.com/books/v3/expenses",
            headers={"Authorization": f"Zoho-oauthtoken {access_token}", "Content-Type": "application/json"},
            params={"organization_id": org_id},
            json=payload,
            timeout=30
        )
        if resp.status_code not in (200, 201):
            return {"success": False, "data": None, "error": f"Create expense failed: {resp.status_code} {resp.text}"}

        data = resp.json()
        if data.get("code") != 0:
            return {"success": False, "data": None, "error": data.get("message")}

        return {"success": True, "data": data.get("expense"), "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
