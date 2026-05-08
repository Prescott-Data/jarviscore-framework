def dropbox_create_folder(auth_info: dict, dropbox_path: str, autorename: bool = False) -> dict:
    import requests
    # dropbox_path must start with "/" e.g. "/Projects/NewFolder"
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        resp = requests.post(
            "https://api.dropboxapi.com/2/files/create_folder_v2",
            json={"path": dropbox_path, "autorename": autorename},
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            timeout=30
        )
        if resp.status_code != 200:
            return {"success": False, "data": None, "error": f"Create folder failed: {resp.status_code} {resp.text}"}

        return {"success": True, "data": resp.json().get("metadata"), "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
