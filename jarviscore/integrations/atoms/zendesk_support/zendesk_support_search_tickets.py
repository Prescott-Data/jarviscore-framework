ATOM_POLICY = {"effect": "read", "approval": "never"}


async def zendesk_support_search_tickets(query: str, timeout: int = 30) -> dict:
    """Search Zendesk Support tickets, preserving result-limit status. See https://developer.zendesk.com/api-reference/ticketing/ticket-management/search/."""
    if not isinstance(query, str) or not query.strip():
        return {"ok": False, "status_code": None, "error": "query is required"}
    requested_types = [
        term.split(":", 1)[1].lower() for term in query.split() if term.lower().startswith("type:")
    ]
    if any(resource_type != "ticket" for resource_type in requested_types):
        return {
            "ok": False,
            "status_code": None,
            "error": "query may only select type:ticket resources",
        }
    ticket_query = query.strip()
    if "type:ticket" not in [term.lower() for term in ticket_query.split()]:
        ticket_query = f"type:ticket {ticket_query}"

    records = []
    total_count = None
    page = 1
    next_page = True
    while page <= 10 and next_page:
        try:
            response = await nexus_call(
                "GET",
                "/api/v2/search.json",
                provider="zendesk_support",
                params={"query": ticket_query, "per_page": 100, "page": page},
                timeout=timeout,
            )
        except Exception as exc:
            return {
                "ok": False,
                "status_code": None,
                "data": {"results": records, "count": total_count, "complete": False},
                "error": str(exc),
            }

        status = response.get("status_code")
        if not isinstance(status, int):
            status = 500
        if not 200 <= status < 300:
            return {
                "ok": False,
                "status_code": status,
                "data": {"results": records, "count": total_count, "complete": False},
                "error": response.get("body") or f"HTTP {status}",
            }

        payload = response.get("json")
        page_records = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(page_records, list):
            return {
                "ok": False,
                "status_code": status,
                "data": {"results": records, "count": total_count, "complete": False},
                "error": "Zendesk returned a response without a results list",
            }
        records.extend(page_records)
        reported_count = payload.get("count")
        if isinstance(reported_count, int):
            total_count = reported_count
        next_page = bool(payload.get("next_page"))
        if not next_page or not page_records:
            break
        page += 1

    complete = not next_page and (total_count is None or len(records) >= total_count)
    if total_count is not None and total_count > 1000:
        complete = False
    result = {
        "ok": True,
        "status_code": 200,
        "data": {
            "results": records,
            "count": total_count if total_count is not None else len(records),
            "complete": complete,
        },
    }
    if not complete:
        result["message"] = (
            "Zendesk search returned a partial result set. The Search API caps "
            "queries at 1000 results; narrow the query before relying on it."
        )
    return result
