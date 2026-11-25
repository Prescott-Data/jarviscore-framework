ATOM_POLICY = {
    "effect": "write",
    "approval": "required",
    "idempotency_fields": ["name"],
    "consequence": "Creates one Gmail label in the person's mailbox; no message is changed.",
}

_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


def _reason(resp: dict) -> str:
    """Google's own reason for a refusal, short."""
    error = ((resp.get("json") or {}).get("error") or {}) if isinstance(resp.get("json"), dict) \
        else {}
    said = error.get("message") if isinstance(error, dict) else None
    return f"{resp.get('status_code')} {said or str(resp.get('body') or '')[:300]}".strip()


async def gmail_create_label(name: str) -> dict:
    """Create one Gmail label by name. Check gmail_list_labels first: a label that already
    exists is returned as it is and nothing is created. No message is touched; apply the
    label with gmail_triage_threads."""
    name = (name or "").strip()
    if not name:
        return {"success": False, "data": None, "error": "a label name is needed"}
    listed = await nexus_call("GET", f"{_BASE}/labels")  # noqa: F821
    if listed["ok"]:
        for label in (listed["json"] or {}).get("labels") or []:
            if (label.get("name") or "").lower() == name.lower():
                return {
                    "success": True,
                    "data": {"id": label.get("id"), "name": label.get("name"), "created": False},
                    "error": None,
                }
    made = await nexus_call(  # noqa: F821
        "POST",
        f"{_BASE}/labels",
        headers={"Content-Type": "application/json"},
        json={"name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"},
    )
    if not made["ok"]:
        return {
            "success": False,
            "data": None,
            "error": f"the label could not be created: {_reason(made)}",
        }
    return {
        "success": True,
        "data": {"id": (made["json"] or {}).get("id"), "name": name, "created": True},
        "error": None,
    }
