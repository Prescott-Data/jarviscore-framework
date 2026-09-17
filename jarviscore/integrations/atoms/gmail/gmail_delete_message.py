ATOM_POLICY = {
    "effect": "destructive",
    "approval": "required",
    "idempotency_fields": ["message_id"],
    "consequence": "Permanently deletes the Gmail message. This cannot be undone.",
}


async def gmail_delete_message(message_id: str) -> dict:
    """Permanently delete one Gmail message. https://developers.google.com/gmail/api/reference/rest/v1/users.messages/delete"""
    response = await nexus_call(
        "DELETE",
        f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}",
    )
    if not response["ok"]:
        return {"success": False, "error": response["body"]}
    return {"success": True, "message_id": message_id, "deleted": True}
