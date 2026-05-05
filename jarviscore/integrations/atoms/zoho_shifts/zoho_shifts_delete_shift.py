def zoho_shifts_delete_shift(auth_info: dict, org_id: str, shift_id: str) -> dict:
    import requests
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        resp = requests.delete(
            f"https://shifts.zoho.com/api/v1/{org_id}/shifts/{shift_id}",
            headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
            timeout=30
        )
        if resp.status_code != 200:
            return {"success": False, "data": None, "error": f"Delete shift failed: {resp.status_code} {resp.text}"}

        return {"success": True, "data": {"shift_id": shift_id, "deleted": True}, "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
