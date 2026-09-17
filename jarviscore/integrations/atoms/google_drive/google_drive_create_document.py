ATOM_POLICY = {
    "effect": "write",
    "approval": "never",
    "idempotency_fields": ["folder_id", "title"],
    "consequence": "Creates one Google Doc in an existing Drive folder.",
}


async def google_drive_create_document(folder_id: str, title: str, content: str) -> dict:
    """Create and populate one Google Doc in an existing Drive folder."""
    metadata = {
        "name": title,
        "mimeType": "application/vnd.google-apps.document",
        "parents": [folder_id],
    }
    created = await nexus_call(
        "POST",
        "https://www.googleapis.com/drive/v3/files",
        headers={"Content-Type": "application/json"},
        params={"fields": "id,name,webViewLink,parents"},
        json=metadata,
    )
    if not created["ok"]:
        return {"success": False, "error": created["body"]}
    document = created["json"]
    document_id = document.get("id")
    populated = await nexus_call(
        "POST",
        f"https://docs.googleapis.com/v1/documents/{document_id}:batchUpdate",
        provider="google_drive",
        headers={"Content-Type": "application/json"},
        json={"requests": [{"insertText": {"location": {"index": 1}, "text": content}}]},
    )
    if not populated["ok"]:
        return {
            "success": False,
            "document_id": document_id,
            "error": populated["body"],
        }
    return {
        "success": True,
        "document_id": document_id,
        "title": document.get("name") or title,
        "web_view_link": document.get("webViewLink"),
        "folder_id": folder_id,
    }