ATOM_POLICY = {
    "effect": "write",
    "approval": "never",
    "idempotency_fields": ["to", "subject", "body", "cc", "bcc"],
    "consequence": "Saves one new draft in the person's Gmail. Nothing is sent.",
}

# The message is built by the standard library (email.message), not by hand: a subject
# with an accent, or a line break in one, arrives as typed and cannot add a header.

_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


def _reason(resp: dict) -> str:
    """Google's own reason for a refusal, short."""
    error = ((resp.get("json") or {}).get("error") or {}) if isinstance(resp.get("json"), dict) \
        else {}
    said = error.get("message") if isinstance(error, dict) else None
    return f"{resp.get('status_code')} {said or str(resp.get('body') or '')[:300]}".strip()


def _addresses(spec) -> list:
    """The email addresses in a comma-separated list (or a list), lower case, in order,
    each once. An entry with no address in it comes back as it was typed, so the caller
    can refuse it by name."""
    from email.utils import getaddresses

    if isinstance(spec, (list, tuple)):
        spec = ", ".join(str(s) for s in spec)
    found = []
    for _, address in getaddresses([str(spec or "")]):
        address = address.strip().lower()
        if address and address not in found:
            found.append(address)
    return found


def _bad(addresses: list) -> list:
    return [a for a in addresses if "@" not in a or " " in a or a.startswith("@")]


def _mime(to: list, subject: str, body: str, cc: list = (), bcc: list = (),
          headers: dict | None = None, subtype: str = "plain") -> str:
    """One message as Gmail's API takes it: RFC 5322, base64url, its body plain text unless
    `subtype` says "html". The standard library writes the headers, so a subject or a name
    with accents arrives as typed."""
    import base64
    from email.message import EmailMessage

    message = EmailMessage()
    message["To"] = ", ".join(to)
    if cc:
        message["Cc"] = ", ".join(cc)
    if bcc:
        message["Bcc"] = ", ".join(bcc)
    message["Subject"] = " ".join(str(subject or "").split())
    for name, value in (headers or {}).items():
        if value:
            message[name] = " ".join(str(value).split())
    message.set_content(str(body or ""), subtype=subtype)
    return base64.urlsafe_b64encode(message.as_bytes()).decode()


async def gmail_create_draft(to: str, subject: str, body: str, cc: str = "",
                              bcc: str = "") -> dict:
    """Save a new email as a draft in the person's Gmail. Nothing is sent: the draft
    waits in Drafts until the person sends it or gmail_send_draft does.

    `to`, `cc` and `bcc` are email addresses, comma-separated. `body` is the plain text of
    the message, as it should read. For an answer to a message use gmail_draft_reply, which
    keeps it in the conversation.

    Returns `draft_id` (what gmail_send_draft takes), `to`, `cc`, `bcc`, `subject`.
    https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.drafts/create
    """
    to_, cc_, bcc_ = _addresses(to), _addresses(cc), _addresses(bcc)
    if not to_ or not str(subject or "").strip() or not str(body or "").strip():
        return {"success": False, "data": None,
                "error": "a recipient in `to`, a subject and a body are all needed"}
    wrong = _bad(to_ + cc_ + bcc_)
    if wrong:
        return {"success": False, "data": None,
                "error": f"not an email address: {', '.join(wrong)}"}
    made = await nexus_call(  # noqa: F821
        "POST",
        f"{_BASE}/drafts",
        headers={"Content-Type": "application/json"},
        json={"message": {"raw": _mime(to_, subject, body, cc_, bcc_)}},
    )
    if not made["ok"]:
        return {"success": False, "data": None,
                "error": f"the draft could not be saved: {_reason(made)}"}
    draft = made["json"] or {}
    return {
        "success": True,
        "data": {
            "draft_id": draft.get("id"),
            "thread_id": (draft.get("message") or {}).get("threadId"),
            "to": to_, "cc": cc_, "bcc": bcc_,
            "subject": " ".join(str(subject).split()),
        },
        "error": None,
    }
