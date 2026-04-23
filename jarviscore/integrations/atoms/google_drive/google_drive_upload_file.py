def gdrive_upload_file(auth_info: dict, file_path: str, folder_id: str = None, file_name: str = None) -> dict:
    import requests
    import os
    scopes = ["https://www.googleapis.com/auth/drive.file"]
    try:
        access_token = _get_nexus_token(auth_info, scopes)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Nexus token error: {str(e)}"}

    try:
        name = file_name or os.path.basename(file_path)
        metadata = {"name": name}
        if folder_id:
            metadata["parents"] = [folder_id]

        with open(file_path, "rb") as f:
            file_content = f.read()

        import mimetypes
        mime_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"

        # multipart upload
        boundary = "boundary_gdrive_upload"
        body = (
            f"--{boundary}\r\n"
            f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
            f'{{"name": "{name}"' + (f', "parents": ["{folder_id}"]' if folder_id else "") + "}\r\n"
            f"--{boundary}\r\n"
            f"Content-Type: {mime_type}\r\n\r\n"
        ).encode() + file_content + f"\r\n--{boundary}--".encode()

        resp = requests.post(
            "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": f"multipart/related; boundary={boundary}"
            },
            data=body,
            timeout=60
        )
        if resp.status_code not in (200, 201):
            return {"success": False, "data": None, "error": f"Upload failed: {resp.status_code} {resp.text}"}

        return {"success": True, "data": resp.json(), "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
