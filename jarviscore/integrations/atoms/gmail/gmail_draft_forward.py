ATOM_POLICY = {
    "effect": "write",
    "approval": "never",
    "idempotency_fields": ["message_id", "to", "note", "cc", "bcc"],
    "consequence": "Saves one draft that forwards a message; never sends.",
}

# The draft carries the message's text under the usual "Forwarded message" lines. Its
# attachments are not carried (an atom cannot pass bytes through nexus_call in the
# sandbox), and the result names them so nobody is told they were.

_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"

_ROOM = 60000  # characters of the original carried; a longer one is cut and says so


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


def _text(payload: dict) -> tuple:
    """A message's text and the names of its attachments: the plain part wherever it sits,
    or, for mail sent as HTML only, the HTML with its tags taken out."""
    import base64
    import html
    import re

    found, files, stack = {"text/plain": [], "text/html": []}, [], [payload or {}]
    while stack:
        part = stack.pop(0)
        stack[0:0] = part.get("parts") or []
        if part.get("filename"):
            files.append(part["filename"])
            continue
        kind = (part.get("mimeType") or "").lower()
        raw = (part.get("body") or {}).get("data") or ""
        if kind in found and raw:
            found[kind].append(
                base64.urlsafe_b64decode(raw + "==").decode("utf-8", errors="ignore"))
    body = "\n".join(found["text/plain"])
    if not body.strip() and found["text/html"]:
        page = "\n".join(found["text/html"])
        page = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", " ", page)
        page = re.sub(r"(?i)<(br|/p|/div|/tr|/li|/h[1-6])\b[^>]*>", "\n", page)
        body = html.unescape(re.sub(r"<[^>]+>", " ", page))
    lines = [" ".join(line.split()) for line in body.replace("\r", "").split("\n")]
    kept = [line for i, line in enumerate(lines) if line or (i and lines[i - 1])]
    return "\n".join(kept).strip(), files


async def gmail_draft_forward(message_id: str, to: str, note: str = "", cc: str = "",
                              bcc: str = "") -> dict:
    """Draft a forward of one message to someone else. The draft is saved, never sent;
    send it with gmail_send_draft when the step asks for it to be sent.

    `message_id` is the message to forward (from gmail_list_headers or
    gmail_read_thread). `to`, `cc` and `bcc` are email addresses, comma-separated. `note`
    is what the person says above the forwarded text; it may be empty. The subject is
    the message's, with "Fwd:".

    The message's text is carried whole. Its attachments are NOT: `attachments_left_out`
    names them, and when it is not empty say so, never that they were forwarded. Returns
    `draft_id` (what gmail_send_draft takes), `to`, `cc`, `bcc`, `subject`.
    https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.drafts/create
    """
    message_id = str(message_id or "").strip()
    to_, cc_, bcc_ = _addresses(to), _addresses(cc), _addresses(bcc)
    if not message_id or not to_:
        return {"success": False, "data": None,
                "error": "a message id and a recipient in `to` are needed"}
    wrong = _bad(to_ + cc_ + bcc_)
    if wrong:
        return {"success": False, "data": None,
                "error": f"not an email address: {', '.join(wrong)}"}
    got = await nexus_call(  # noqa: F821
        "GET", f"{_BASE}/messages/{message_id}", params={"format": "full"})
    if not got["ok"]:
        return {"success": False, "data": None,
                "error": f"the message could not be read: {_reason(got)}"}
    payload = (got["json"] or {}).get("payload") or {}
    headers = {h.get("name", "").lower(): h.get("value", "")
               for h in payload.get("headers") or []}
    text, files = _text(payload)
    cut = len(text) > _ROOM
    subject = headers.get("subject") or ""
    if not subject.lower().startswith(("fwd:", "fw:")):
        subject = f"Fwd: {subject}"
    lines = [str(note or "").strip(), "", "---------- Forwarded message ---------",
             f"From: {headers.get('from', '')}", f"Date: {headers.get('date', '')}",
             f"Subject: {headers.get('subject', '')}", f"To: {headers.get('to', '')}"]
    if headers.get("cc"):
        lines.append(f"Cc: {headers['cc']}")
    lines += ["", text[:_ROOM] + ("\n[the rest of the message was cut here]" if cut else "")]
    made = await nexus_call(  # noqa: F821
        "POST",
        f"{_BASE}/drafts",
        headers={"Content-Type": "application/json"},
        json={"message": {"raw": _mime(to_, subject, "\n".join(lines).strip(), cc_, bcc_)}},
    )
    if not made["ok"]:
        return {"success": False, "data": None,
                "error": f"the draft could not be saved: {_reason(made)}"}
    draft = made["json"] or {}
    out = {
        "draft_id": draft.get("id"),
        "to": to_, "cc": cc_, "bcc": bcc_,
        "subject": " ".join(subject.split()),
        "attachments_left_out": files,
        "text_cut": cut,
    }
    if files:
        out["note"] = ("The original's attachments are not in this draft: "
                       + ", ".join(files) + ". Say so.")
    return {"success": True, "data": out, "error": None}
