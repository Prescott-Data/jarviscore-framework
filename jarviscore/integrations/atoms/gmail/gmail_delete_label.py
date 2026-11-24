ATOM_POLICY = {
    "effect": "destructive",
    "approval": "required",
    "idempotency_fields": ["name"],
    "consequence": (
        "Deletes one Gmail label from the person's mailbox. The label comes off every "
        "message that has it; no message is deleted."
    ),
}

_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


def _reason(resp: dict) -> str:
    """Google's own reason for a refusal, short."""
    error = ((resp.get("json") or {}).get("error") or {}) if isinstance(resp.get("json"), dict) \
        else {}
    said = error.get("message") if isinstance(error, dict) else None
    return f"{resp.get('status_code')} {said or str(resp.get('body') or '')[:300]}".strip()


async def gmail_delete_label(name: str) -> dict:
    """Delete one of the person's own Gmail labels by name. The messages stay; they only
    lose the label. Gmail's system labels (INBOX, STARRED and the rest) cannot be deleted."""
    name = (name or "").strip()
    if not name:
        return {"success": False, "data": None, "error": "a label name is needed"}
    listed = await nexus_call("GET", f"{_BASE}/labels")  # noqa: F821
    if not listed["ok"]:
        return {
            "success": False,
            "data": None,
            "error": f"labels could not be listed: {_reason(listed)}",
        }
    found = next(
        (
            label
            for label in (listed["json"] or {}).get("labels") or []
            if (label.get("name") or "").lower() == name.lower()
        ),
        None,
    )
    if found is None:
        return {"success": False, "data": None, "error": f"no label named {name!r}"}
    if found.get("type") != "user":
        return {"success": False, "data": None, "error": f"{name} is Gmail's own label"}
    gone = await nexus_call("DELETE", f"{_BASE}/labels/{found['id']}")  # noqa: F821
    if not gone["ok"]:
        return {
            "success": False,
            "data": None,
            "error": f"the label could not be deleted: {_reason(gone)}",
        }
    return {"success": True, "data": {"name": found.get("name"), "deleted": True}, "error": None}
