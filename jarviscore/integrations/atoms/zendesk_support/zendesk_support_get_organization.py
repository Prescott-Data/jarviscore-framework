ATOM_POLICY = {"effect": "read", "approval": "never"}


async def zendesk_support_get_organization(organization_id: int, timeout: int = 30) -> dict:
    """Read one organization. See https://developer.zendesk.com/api-reference/ticketing/organizations/organizations/."""
    if (
        isinstance(organization_id, bool)
        or not isinstance(organization_id, int)
        or organization_id <= 0
    ):
        return {
            "ok": False,
            "status_code": None,
            "error": "organization_id must be a positive integer",
        }
    try:
        response = await nexus_call(
            "GET",
            f"/api/v2/organizations/{organization_id}.json",
            provider="zendesk_support",
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
