def zoho_books_get_expenses(auth_info: dict, org_id: str, status: str = None) -> dict:
    import requests
    # status: unbilled, invoiced, reimbursed, non-billable
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        params = {"organization_id": org_id}
        if status:
            params["filter_by"] = f"Status.{status.capitalize()}"

        resp = requests.get(
            "https://www.zohoapis.com/books/v3/expenses",
            headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
            params=params,
            timeout=30
        )
        if resp.status_code != 200:
            return {"success": False, "data": None, "error": f"Get expenses failed: {resp.status_code} {resp.text}"}

        data = resp.json()
        if data.get("code") != 0:
            return {"success": False, "data": None, "error": data.get("message")}

        expenses = data.get("expenses", [])
        return {"success": True, "data": {"expenses": expenses, "count": len(expenses)}, "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
