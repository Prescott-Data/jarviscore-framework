def gdrive_download_file(auth_info: dict, file_id: str, destination_path: str) -> dict:
    import requests
    import os
    scopes = ["https://www.googleapis.com/auth/drive.readonly"]
    try:
        access_token = _get_nexus_token(auth_info, scopes)
    except Exception as e:
        return {"success": False, "file_id": file_id, "data": None, "error": f"Nexus token error: {str(e)}"}

    try:
        resp = requests.get(
            f"https://www.googleapis.com/drive/v3/files/{file_id}",
            params={"alt": "media"},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=60,
            stream=True
        )
        if resp.status_code != 200:
            return {"success": False, "file_id": file_id, "data": None, "error": f"Download failed: {resp.status_code} {resp.text}"}

        os.makedirs(os.path.dirname(destination_path), exist_ok=True) if os.path.dirname(destination_path) else None
        with open(destination_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        return {"success": True, "file_id": file_id, "data": {"destination_path": destination_path}, "error": None}

    except Exception as e:
        return {"success": False, "file_id": file_id, "data": None, "error": str(e)}
