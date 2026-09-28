ATOM_POLICY = {
    "effect": "write",
    "approval": "required",
    "idempotency_fields": ["ticket_id", "body"],
    "consequence": "Adds a private internal note to the Zendesk ticket.",
}


async def zendesk_support_post_internal_note(ticket_id: int, body: str, timeout: int = 30) -> dict:
    """Add a private ticket note after approval. See https://developer.zendesk.com/api-reference/ticketing/tickets/tickets/."""
    if isinstance(ticket_id, bool) or not isinstance(ticket_id, int) or ticket_id <= 0:
        return {"ok": False, "status_code": None, "error": "ticket_id must be a positive integer"}
    if not isinstance(body, str) or not body.strip():
        return {"ok": False, "status_code": None, "error": "body is required"}
    try:
        response = await nexus_call(
            "PUT",
            f"/api/v2/tickets/{ticket_id}.json",
            provider="zendesk_support",
            json={"ticket": {"comment": {"body": body, "public": False}}},
            timeout=timeout,
        )
        return _response_result(response)
    except Exception as exc:
        return {"ok": False, "status_code": None, "error": str(exc)}


def _response_result(response):
    status = response.get("status_code")
    if not isinstance(status, int):
        status = 500
    result = {
        "ok": 200 <= status < 300,
        "status_code": status,
        "data": response.get("json"),
    }
    if not result["ok"]:
        result["error"] = response.get("body") or f"HTTP {status}"
    return result
