ATOM_POLICY = {"effect": "read", "approval": "never"}


async def zendesk_support_get_ticket_comments(ticket_id: int, timeout: int = 30) -> dict:
    """Read every ticket comment using Zendesk cursor pagination. See https://developer.zendesk.com/api-reference/ticketing/tickets/ticket_comments/."""
    if isinstance(ticket_id, bool) or not isinstance(ticket_id, int) or ticket_id <= 0:
        return {"ok": False, "status_code": None, "error": "ticket_id must be a positive integer"}

    comments = []
    params = {"page[size]": 100}
    cursors = set()
    pages = 0
    while True:
        try:
            response = await nexus_call(
                "GET",
                f"/api/v2/tickets/{ticket_id}/comments.json",
                provider="zendesk_support",
                params=params,
                timeout=timeout,
            )
        except Exception as exc:
            return {
                "ok": False,
                "status_code": None,
                "data": {"comments": comments, "complete": False},
                "error": str(exc),
            }

        status = response.get("status_code")
        if not isinstance(status, int):
            status = 500
        if not 200 <= status < 300:
            return {
                "ok": False,
                "status_code": status,
                "data": {"comments": comments, "complete": False},
                "error": response.get("body") or f"HTTP {status}",
            }

        payload = response.get("json")
        page_comments = payload.get("comments") if isinstance(payload, dict) else None
        if not isinstance(page_comments, list):
            return {
                "ok": False,
                "status_code": status,
                "data": {"comments": comments, "complete": False},
                "error": "Zendesk returned a response without a comments list",
            }
        comments.extend(page_comments)

        meta = payload.get("meta") or {}
        if not meta.get("has_more"):
            return {
                "ok": True,
                "status_code": status,
                "data": {"comments": comments, "count": len(comments), "complete": True},
            }

        cursor = meta.get("after_cursor")
        if not isinstance(cursor, str) or not cursor or cursor in cursors:
            return {
                "ok": False,
                "status_code": status,
                "data": {"comments": comments, "count": len(comments), "complete": False},
                "error": "Zendesk reports more comments but returned no new cursor; narrow the request or retry.",
            }
        cursors.add(cursor)
        pages += 1
        if pages >= 50:
            return {
                "ok": False,
                "status_code": status,
                "data": {"comments": comments, "count": len(comments), "complete": False},
                "error": "Zendesk returned more than 5000 comments; the API limit prevents a complete result.",
            }
        params["page[after]"] = cursor
