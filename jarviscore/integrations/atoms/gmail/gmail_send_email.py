ATOM_POLICY = {
    "effect": "notify",
    "approval": "required",
    "idempotency_fields": ["to", "subject", "body", "cc", "bcc"],
    "consequence": (
        "Sends one email from the person's Gmail, in their name. A sent email cannot "
        "be recalled."
    ),
}

# The message is built by the standard library (email.message), not by hand, and takes cc
# and bcc. The call's arguments say who it goes to and how it begins (_consequence).

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


def _shown(people: list, most: int = 8) -> str:
    people = list(people)
    more = len(people) - most
    return ", ".join(people[:most]) + (f" and {more} more" if more > 0 else "")


def _consequence(params: dict) -> str:
    """What the approval request says this call does, from its arguments alone: who it goes
    to first, then the subject, then how the text begins."""
    said = "Sends an email in the person's name to: " + (
        _shown(_addresses(params.get("to"))) or "nobody")
    for name in ("cc", "bcc"):
        people = _addresses(params.get(name))
        if people:
            said += f"; {name}: {_shown(people)}"
    body = " ".join(str(params.get("body") or "").split())
    opening = body[:500] + ("…" if len(body) > 500 else "")
    subject = " ".join(str(params.get("subject") or "").split())[:150]
    return (f'{said}. Subject: "{subject}". It reads: "{opening}" '
            f"({len(body)} characters in all). A sent email cannot be recalled.")


async def gmail_send_email(to: str, subject: str, body: str, cc: str = "", bcc: str = "",
                           body_type: str = "text/plain") -> dict:
    """Send a new email from the person's Gmail, in their name. It waits for the
    person's approval, which shows the recipients, the subject and how it begins.

    `to`, `cc` and `bcc` are email addresses, comma-separated. `body` is the plain text,
    exactly as it should be read: what is approved is what is sent. `body_type`
    "text/html" sends `body` as HTML instead. Use this only for a
    new conversation; an answer or a forward is drafted in its conversation
    (gmail_draft_reply, gmail_draft_forward) and sent with gmail_send_draft.

    Returns `message_id`, `thread_id`, and `to`, `cc`, `bcc`, `subject` as sent.
    https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/send
    """
    to_, cc_, bcc_ = _addresses(to), _addresses(cc), _addresses(bcc)
    if not to_ or not str(subject or "").strip() or not str(body or "").strip():
        return {"success": False, "data": None,
                "error": "a recipient in `to`, a subject and a body are all needed"}
    wrong = _bad(to_ + cc_ + bcc_)
    if wrong:
        return {"success": False, "data": None,
                "error": f"not an email address: {', '.join(wrong)}"}
    kind = str(body_type or "text/plain").strip().lower()
    if kind not in ("text/plain", "text/html"):
        return {"success": False, "data": None,
                "error": 'body_type is "text/plain" or "text/html"'}
    sent = await nexus_call(  # noqa: F821
        "POST",
        f"{_BASE}/messages/send",
        headers={"Content-Type": "application/json"},
        json={"raw": _mime(to_, subject, body, cc_, bcc_, subtype=kind.split("/")[1])},
    )
    if not sent["ok"]:
        return {"success": False, "data": None,
                "error": f"the email was not sent: {_reason(sent)}"}
    message = sent["json"] or {}
    return {
        "success": True,
        "data": {
            "sent": True,
            "message_id": message.get("id"),
            "thread_id": message.get("threadId"),
            "to": to_, "cc": cc_, "bcc": bcc_,
            "subject": " ".join(str(subject).split()),
        },
        "error": None,
    }
