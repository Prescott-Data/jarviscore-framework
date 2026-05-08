def dropbox_download_file(auth_info: dict, dropbox_path: str, destination_path: str) -> dict:
    import requests
    import os
    # dropbox_path must start with "/" e.g. "/folder/file.txt"
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        resp = requests.post(
            "https://content.dropboxapi.com/2/files/download",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Dropbox-API-Arg": f'{{"path": "{dropbox_path}"}}'
            },
            timeout=60
        )
        if resp.status_code != 200:
            return {"success": False, "data": None, "error": f"Download failed: {resp.status_code} {resp.text}"}

        os.makedirs(os.path.dirname(os.path.abspath(destination_path)), exist_ok=True)
        with open(destination_path, "wb") as f:
            f.write(resp.content)

        return {"success": True, "data": {"destination_path": destination_path, "bytes": len(resp.content)}, "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
