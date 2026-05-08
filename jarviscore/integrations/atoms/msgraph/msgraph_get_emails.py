def msgraph_get_emails(auth_info: dict, max_results: int = 20, folder: str = "inbox") -> dict:
    import requests
    # folder: inbox, sentitems, drafts, deleteditems
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        resp = requests.get(
            f"https://graph.microsoft.com/v1.0/me/mailFolders/{folder}/messages",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"$top": max_results, "$orderby": "receivedDateTime desc", "$select": "id,subject,from,receivedDateTime,isRead,bodyPreview"},
            timeout=30
        )
        if resp.status_code != 200:
            return {"success": False, "data": None, "error": f"Get emails failed: {resp.status_code} {resp.text}"}

        emails = resp.json().get("value", [])
        return {"success": True, "data": {"emails": emails, "count": len(emails)}, "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
