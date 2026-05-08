def azure_storage_upload_blob(auth_info: dict, account_name: str, container_name: str, blob_name: str, content: bytes, content_type: str = "application/octet-stream") -> dict:
    import requests
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        resp = requests.put(
            f"https://{account_name}.blob.core.windows.net/{container_name}/{blob_name}",
            headers={
                "Authorization": f"Bearer {access_token}",
                "x-ms-version": "2020-10-02",
                "x-ms-blob-type": "BlockBlob",
                "Content-Type": content_type
            },
            data=content,
            timeout=60
        )
        if resp.status_code != 201:
            return {"success": False, "data": None, "error": f"Upload blob failed: {resp.status_code} {resp.text}"}

        return {"success": True, "data": {"account": account_name, "container": container_name, "blob": blob_name, "uploaded": True}, "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
