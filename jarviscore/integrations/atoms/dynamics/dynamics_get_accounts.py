def dynamics_get_accounts(auth_info: dict, org_url: str, max_results: int = 50) -> dict:
    import requests
    # org_url: e.g. https://yourorg.api.crm.dynamics.com
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        resp = requests.get(
            f"{org_url.rstrip('/')}/api/data/v9.2/accounts",
            headers={"Authorization": f"Bearer {access_token}", "OData-MaxVersion": "4.0", "OData-Version": "4.0", "Accept": "application/json"},
            params={"$top": max_results, "$select": "accountid,name,emailaddress1,telephone1,websiteurl"},
            timeout=30
        )
        if resp.status_code != 200:
            return {"success": False, "data": None, "error": f"Get accounts failed: {resp.status_code} {resp.text}"}

        accounts = resp.json().get("value", [])
        return {"success": True, "data": {"accounts": accounts, "count": len(accounts)}, "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
