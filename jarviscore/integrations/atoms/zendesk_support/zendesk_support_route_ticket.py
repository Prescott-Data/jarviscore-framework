ATOM_POLICY = {
    "effect": "write",
    "approval": "required",
    "idempotency_fields": ["ticket_id", "group_id", "priority"],
    "consequence": "Assigns a Zendesk ticket to a support group and sets its priority.",
}


async def zendesk_support_route_ticket(
    ticket_id: int, group_id: int, priority: str = "normal", timeout: int = 30,
) -> dict:
    """Route an existing ticket. https://developer.zendesk.com/api-reference/ticketing/tickets/tickets/#update-ticket"""
    if any(isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in (ticket_id, group_id)):
        return {"ok": False, "status_code": None, "error": "positive ticket_id and group_id required"}
    if priority not in {"low", "normal", "high", "urgent"}:
        return {"ok": False, "status_code": None, "error": "invalid priority"}
    response = await nexus_call(
        "PUT", f"/api/v2/tickets/{ticket_id}.json", provider="zendesk_support", timeout=timeout,
        json={"ticket": {"group_id": group_id, "priority": priority}},
    )
    status = response.get("status_code")
    return {
        "ok": isinstance(status, int) and 200 <= status < 300,
        "status_code": status, "data": response.get("json"),
        "error": None if isinstance(status, int) and 200 <= status < 300 else response.get("body"),
    }
