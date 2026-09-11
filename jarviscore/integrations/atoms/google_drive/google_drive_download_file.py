async def google_drive_download_file(file_id: str, destination_path: str) -> dict:
    """Download one Drive file to a sandbox path."""
    import os
    try:
        resp = await nexus_call(
            'GET',
            f"https://www.googleapis.com/drive/v3/files/{file_id}",
            params={"alt": "media"},
            provider='google_drive',
        )
        if not resp['ok']:
            return {"success": False, "file_id": file_id, "data": None, "error": resp['body']}

        os.makedirs(os.path.dirname(destination_path), exist_ok=True) if os.path.dirname(destination_path) else None
        with open(destination_path, "wb") as f:
            f.write(resp['content'])

        return {"success": True, "file_id": file_id, "data": {"destination_path": destination_path, "bytes": len(resp['content'])}, "error": None}

    except Exception as e:
        return {"success": False, "file_id": file_id, "data": None, "error": str(e)}
