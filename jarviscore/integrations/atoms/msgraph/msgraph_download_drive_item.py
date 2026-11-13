ATOM_POLICY = {"effect": "read", "approval": "never"}


async def msgraph_download_drive_item(item_id: str, drive_id: str = "", destination_path: str = "", max_bytes: int = 16777216) -> dict:
    """Read original driveItem bytes through bounded native Nexus; optionally save a relative output artifact."""
    import base64

    from jarviscore.integrations.original_files import (
        byte_limit,
        destination,
        identifier,
        original_bytes,
        write_original,
    )

    try:
        byte_limit(max_bytes)
        encoded_item = identifier(item_id)
        if not isinstance(drive_id, str):
            raise TypeError("Invalid drive identifier")
        selected = None if destination_path == "" else destination(destination_path, globals().get("output_dir"))
        if drive_id:
            encoded_drive = identifier(drive_id)
            response = await nexus_call(  # noqa: F821 - injected native credential boundary
                "GET", f"https://graph.microsoft.com/v1.0/drives/{encoded_drive}/items/{encoded_item}/content",
                provider="msgraph", original_download=True, max_bytes=max_bytes,
            )
        else:
            response = await nexus_call(  # noqa: F821 - injected native credential boundary
                "GET", f"https://graph.microsoft.com/v1.0/me/drive/items/{encoded_item}/content",
                provider="msgraph", original_download=True, max_bytes=max_bytes,
            )
        content = original_bytes(response, max_bytes)
        data = {"content_base64": base64.b64encode(content).decode("ascii"), "byte_count": len(content)}
        if selected is not None:
            write_original(content, selected)
            data["destination_path"] = destination_path
        return {"success": True, "data": data, "error": None}
    except Exception:  # noqa: BLE001 - transport/file errors must not expose private capabilities
        return {"success": False, "data": None, "error": "Original download failed"}
