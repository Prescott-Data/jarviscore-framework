ATOM_POLICY = {
    "effect": "read",
    "approval": "never",
}


async def dropbox_download_file(dropbox_path: str, destination_path: str, max_bytes: int = 16777216) -> dict:
    """Download original Dropbox bytes through a verified native bounded read POST; never follow redirects."""
    import json

    from jarviscore.integrations.original_files import (
        byte_limit,
        destination,
        original_bytes,
        write_original,
    )

    try:
        byte_limit(max_bytes)
        if not isinstance(dropbox_path, str) or not dropbox_path:
            raise ValueError("Invalid Dropbox selector")
        selected = destination(destination_path, globals().get("output_dir"), relative_only=False)
        resp = await nexus_call(  # noqa: F821 - injected native credential boundary
            "POST", "https://content.dropboxapi.com/2/files/download",
            headers={"Dropbox-API-Arg": json.dumps({"path": dropbox_path})},
            provider="dropbox", original_download=True, max_bytes=max_bytes,
        )
        if resp.get("status_code") != 200:
            raise ValueError("Original download failed")
        content = original_bytes(resp, max_bytes)
        write_original(content, selected)
        return {"success": True, "data": {"destination_path": destination_path, "bytes": len(content)}, "error": None}
    except Exception:  # noqa: BLE001 - transport/file errors must not expose private capabilities
        return {"success": False, "data": None, "error": "Original download failed"}
