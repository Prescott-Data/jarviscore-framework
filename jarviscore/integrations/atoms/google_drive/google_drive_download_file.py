ATOM_POLICY = {"effect": "read", "approval": "never"}


async def google_drive_download_file(file_id: str, destination_path: str, max_bytes: int = 16777216) -> dict:
    """Download an original Drive blob through bounded native Nexus to an exclusive sandbox artifact."""
    from jarviscore.integrations.original_files import (
        byte_limit,
        destination,
        identifier,
        original_bytes,
        write_original,
    )

    try:
        byte_limit(max_bytes)
        encoded_id = identifier(file_id)
        selected = destination(destination_path, globals().get("output_dir"), relative_only=False)
        resp = await nexus_call(  # noqa: F821 - injected native credential boundary
            "GET", f"https://www.googleapis.com/drive/v3/files/{encoded_id}",
            params={"alt": "media"}, provider="google_drive", original_download=True, max_bytes=max_bytes,
        )
        content = original_bytes(resp, max_bytes)
        write_original(content, selected)
        return {"success": True, "file_id": file_id, "data": {"destination_path": destination_path, "bytes": len(content)}, "error": None}
    except Exception:  # noqa: BLE001 - transport/file errors must not expose private capabilities
        return {"success": False, "file_id": file_id, "data": None, "error": "Original download failed"}
