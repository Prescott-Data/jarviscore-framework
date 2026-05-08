def azure_storage_download_blob(auth_info: dict, account_name: str, container_name: str, blob_name: str) -> dict:
    import requests
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        resp = requests.get(
            f"https://{account_name}.blob.core.windows.net/{container_name}/{blob_name}",
            headers={"Authorization": f"Bearer {access_token}", "x-ms-version": "2020-10-02"},
            timeout=60
        )
        if resp.status_code != 200:
            return {"success": False, "data": None, "error": f"Download blob failed: {resp.status_code} {resp.text}"}

        return {"success": True, "data": {"blob_name": blob_name, "content_type": resp.headers.get("Content-Type"), "content": resp.content.decode("utf-8", errors="replace"), "size_bytes": len(resp.content)}, "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
