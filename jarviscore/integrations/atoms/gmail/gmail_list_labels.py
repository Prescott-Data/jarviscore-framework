ATOM_POLICY = {
    "effect": "read",
    "approval": "never",
}

_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


def _reason(resp: dict) -> str:
    """Google's own reason for a refusal, short."""
    error = ((resp.get("json") or {}).get("error") or {}) if isinstance(resp.get("json"), dict) \
        else {}
    said = error.get("message") if isinstance(error, dict) else None
    return f"{resp.get('status_code')} {said or str(resp.get('body') or '')[:300]}".strip()


async def gmail_list_labels() -> dict:
    """List the mailbox's labels by name: the person's own labels and Gmail's system ones
    (INBOX, UNREAD, STARRED, IMPORTANT). Use it to see whether a label exists before
    applying or creating one."""
    listed = await nexus_call("GET", f"{_BASE}/labels")  # noqa: F821
    if not listed["ok"]:
        return {
            "success": False,
            "data": None,
            "error": f"labels could not be listed: {_reason(listed)}",
        }
    labels = (listed["json"] or {}).get("labels") or []
    return {
        "success": True,
        "data": {
            "user": sorted(x.get("name", "") for x in labels if x.get("type") == "user"),
            "system": sorted(x.get("name", "") for x in labels if x.get("type") != "user"),
        },
        "error": None,
    }
