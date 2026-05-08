def gdrive_create_folder(auth_info: dict, folder_name: str, parent_folder_id: str = None) -> dict:
    import requests
    scopes = ["https://www.googleapis.com/auth/drive"]
    try:
        access_token = _get_nexus_token(auth_info, scopes)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Nexus token error: {str(e)}"}

    try:
        metadata = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder"
        }
        if parent_folder_id:
            metadata["parents"] = [parent_folder_id]

        resp = requests.post(
            "https://www.googleapis.com/drive/v3/files",
            json=metadata,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            },
            timeout=30
        )
        if resp.status_code not in (200, 201):
            return {"success": False, "data": None, "error": f"Create folder failed: {resp.status_code} {resp.text}"}

        return {"success": True, "data": resp.json(), "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
