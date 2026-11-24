ATOM_POLICY = {
    "effect": "write",
    "approval": "never",
    "idempotency_fields": ["message_id", "body", "reply_all", "cc", "bcc"],
    "consequence": "Saves one draft as a reply in the message's conversation; never sends.",
}

# A reply belongs in the conversation. This drafts to the sender of `message_id` (and, for
# reply-all, to everyone else on it), in its thread, with the headers a mail client sets
# (In-Reply-To, References), so it opens as a reply. Who it goes to is worked out here from
# the message, never typed by the caller.

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


async def gmail_draft_reply(message_id: str, body: str, reply_all: bool = False,
                            cc: str = "", bcc: str = "") -> dict:
    """Draft a reply to one message, inside its conversation. The draft is saved, never
    sent; send it with gmail_send_draft when the step asks for it to be sent.

    `message_id` is the message being answered (from gmail_list_headers or
    gmail_read_thread). `body` is the plain text of the reply. It is addressed to the
    message's sender (its Reply-To when it has one). `reply_all` true also copies everyone
    who was on the message (its To and Cc), without the person's own address. When the
    message is one the person sent, the reply is a follow-up: it goes to the people
    that message went to. `cc` and
    `bcc` add more addresses, comma-separated. The subject is the message's, with "Re:".

    Returns `draft_id` (what gmail_send_draft takes), `thread_id`, and `to`, `cc`, `bcc`
    and `subject` as the draft has them: report who it is addressed to.
    https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.drafts/create
    """
    message_id = str(message_id or "").strip()
    if not message_id or not str(body or "").strip():
        return {"success": False, "data": None, "error": "a message id and a body are needed"}
    extra_cc, extra_bcc = _addresses(cc), _addresses(bcc)
    wrong = _bad(extra_cc + extra_bcc)
    if wrong:
        return {"success": False, "data": None,
                "error": f"not an email address: {', '.join(wrong)}"}
    got = await nexus_call(  # noqa: F821
        "GET",
        f"{_BASE}/messages/{message_id}",
        params={
            "format": "metadata",
            "metadataHeaders": ["From", "Reply-To", "To", "Cc", "Subject", "Message-ID",
                                "References"],
        },
    )
    if not got["ok"]:
        return {"success": False, "data": None,
                "error": f"the message could not be read: {_reason(got)}"}
    message = got["json"] or {}
    headers = {
        h.get("name", "").lower(): h.get("value", "")
        for h in (message.get("payload") or {}).get("headers") or []
    }
    sender = _addresses(headers.get("reply-to") or headers.get("from") or "")
    if not sender:
        return {"success": False, "data": None, "error": "the message has no sender to reply to"}
    own = await nexus_call("GET", f"{_BASE}/profile")  # noqa: F821
    if not own["ok"]:
        return {"success": False, "data": None,
                "error": f"the person's own address could not be read: {_reason(own)}"}
    me = str((own["json"] or {}).get("emailAddress") or "").lower()
    to_line, cc_line = _addresses(headers.get("to")), _addresses(headers.get("cc"))
    # A reply to a message the person sent goes on to the people it was sent to (a
    # follow-up), as a mail client does it, not back to the person.
    theirs = [a for a in to_line if a != me]
    if _addresses(headers.get("from")) == [me] and theirs:
        to_, others = theirs, cc_line
    else:
        to_, others = sender, to_line + cc_line
    cc_ = [a for a in others if a != me and a not in to_] if reply_all is True else []
    cc_ = list(dict.fromkeys(cc_))
    cc_ += [a for a in extra_cc if a not in to_ and a not in cc_]
    subject = headers.get("subject") or ""
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"
    original = headers.get("message-id") or ""
    threading = {}
    if original:
        references = " ".join(x for x in (headers.get("references") or "", original) if x)
        threading = {"In-Reply-To": original, "References": references}
    made = await nexus_call(  # noqa: F821
        "POST",
        f"{_BASE}/drafts",
        headers={"Content-Type": "application/json"},
        json={"message": {
            "raw": _mime(to_, subject, body, cc_, extra_bcc, threading),
            "threadId": message.get("threadId"),
        }},
    )
    if not made["ok"]:
        return {"success": False, "data": None,
                "error": f"the draft could not be saved: {_reason(made)}"}
    draft = made["json"] or {}
    return {
        "success": True,
        "data": {
            "draft_id": draft.get("id"),
            "thread_id": message.get("threadId"),
            "to": to_, "cc": cc_, "bcc": extra_bcc,
            "subject": " ".join(subject.split()),
        },
        "error": None,
    }
