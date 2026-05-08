def dropbox_upload_file(auth_info: dict, file_path: str, dropbox_path: str, overwrite: bool = True) -> dict:
    import requests
    import os
    # dropbox_path must start with "/" e.g. "/folder/file.txt"
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        mode = "overwrite" if overwrite else "add"
        with open(file_path, "rb") as f:
            resp = requests.post(
                "https://content.dropboxapi.com/2/files/upload",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/octet-stream",
                    "Dropbox-API-Arg": f'{{"path": "{dropbox_path}", "mode": "{mode}", "autorename": true}}'
                },
                data=f,
                timeout=60
            )
        if resp.status_code != 200:
            return {"success": False, "data": None, "error": f"Upload failed: {resp.status_code} {resp.text}"}

        return {"success": True, "data": resp.json(), "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
