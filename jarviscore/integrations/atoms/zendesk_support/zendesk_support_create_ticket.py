ATOM_POLICY = {
    "effect": "write",
    "approval": "required",
    "idempotency_fields": ["external_id"],
    "consequence": "Creates a Zendesk support ticket and routes it to a support group.",
}


async def zendesk_support_create_ticket(
    subject: str, body: str, requester_name: str, requester_email: str,
    external_id: str, group_id: int, priority: str = "normal", timeout: int = 30,
) -> dict:
    """Create a ticket with a private conversation transcript. https://developer.zendesk.com/documentation/ticketing/managing-tickets/creating-and-updating-tickets/"""
    for value in (subject, body, requester_name, requester_email, external_id):
        if not isinstance(value, str) or not value.strip():
            return {"ok": False, "status_code": None, "error": "non-empty ticket fields required"}
    if isinstance(group_id, bool) or not isinstance(group_id, int) or group_id <= 0:
        return {"ok": False, "status_code": None, "error": "group_id must be a positive integer"}
    if priority not in {"low", "normal", "high", "urgent"}:
        return {"ok": False, "status_code": None, "error": "invalid priority"}
    response = await nexus_call(
        "POST", "/api/v2/tickets.json", provider="zendesk_support", timeout=timeout,
        json={"ticket": {
            "subject": subject, "comment": {"body": body, "public": False},
            "requester": {"name": requester_name, "email": requester_email},
            "external_id": external_id, "group_id": group_id,
            "priority": priority, "status": "open", "tags": ["support_chat"],
        }},
    )
    status = response.get("status_code")
    return {
        "ok": isinstance(status, int) and 200 <= status < 300,
        "status_code": status, "data": response.get("json"),
        "error": None if isinstance(status, int) and 200 <= status < 300 else response.get("body"),
    }
