def zoho_books_get_invoices(auth_info: dict, org_id: str, status: str = None) -> dict:
    import requests
    # status: draft, sent, overdue, paid, void, unpaid, partially_paid, viewed
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        params = {"organization_id": org_id}
        if status:
            params["status"] = status

        resp = requests.get(
            "https://www.zohoapis.com/books/v3/invoices",
            headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
            params=params,
            timeout=30
        )
        if resp.status_code != 200:
            return {"success": False, "data": None, "error": f"Get invoices failed: {resp.status_code} {resp.text}"}

        data = resp.json()
        if data.get("code") != 0:
            return {"success": False, "data": None, "error": data.get("message")}

        invoices = data.get("invoices", [])
        return {"success": True, "data": {"invoices": invoices, "count": len(invoices)}, "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
