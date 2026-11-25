ATOM_POLICY = {
    "effect": "notify",
    "approval": "required",
    "idempotency_fields": ["draft_id"],
    "consequence": (
        "Sends one draft from the person's Gmail, in their name, as it stands. A sent "
        "email cannot be recalled."
    ),
}

# The draft is what the person read; sending the draft itself (drafts.send) sends that,
# in its conversation, and nothing retyped. The call names who it goes to, its subject and
# how it begins, so the approval request can show them, and the draft is read first: when any
# of the three is not the draft's own, nothing is sent.

_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"

_LEAST = 40  # characters of the draft's beginning the call must give (or all of a shorter one)


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


def _draft(draft: dict) -> dict:
    """A draft as the person would recognise it: who it goes to, its subject, how it
    begins, and its text with the line breaks taken out (what an approval request can be
    checked by)."""
    message = draft.get("message") or {}
    headers = {h.get("name", "").lower(): h.get("value", "")
               for h in (message.get("payload") or {}).get("headers") or []}
    text, files = _text(message.get("payload") or {})
    return {
        "draft_id": draft.get("id"),
        "thread_id": message.get("threadId"),
        "to": _addresses(headers.get("to")),
        "cc": _addresses(headers.get("cc")),
        "bcc": _addresses(headers.get("bcc")),
        "subject": " ".join((headers.get("subject") or "").split()),
        "is_reply": bool(headers.get("in-reply-to")),
        "text": " ".join(text.split()),
        "attachments": files,
    }


def _shown(people: list, most: int = 8) -> str:
    people = list(people)
    more = len(people) - most
    return ", ".join(people[:most]) + (f" and {more} more" if more > 0 else "")


def _consequence(params: dict) -> str:
    """What the approval request says this call does, from its arguments alone: who it goes
    to first, then the subject, then how the text begins."""
    said = "Sends the draft, in the person's name, to: " + (
        _shown(_addresses(params.get("to"))) or "nobody")
    for name in ("cc", "bcc"):
        people = _addresses(params.get(name))
        if people:
            said += f"; {name}: {_shown(people)}"
    opening = " ".join(str(params.get("opening") or "").split())
    opening = opening[:500] + ("…" if len(opening) > 500 else "")
    subject = " ".join(str(params.get("subject") or "").split())[:150]
    return (f'{said}. Subject: "{subject}". It begins: "{opening}" The whole draft is '
            "sent as it stands in Gmail. A sent email cannot be recalled.")


async def gmail_send_draft(draft_id: str, to: str, subject: str, opening: str,
                           cc: str = "", bcc: str = "") -> dict:
    """Send a draft that is already in the person's Gmail, exactly as it stands, in
    its conversation when it is a reply. It waits for the person's approval, which shows
    who it goes to, the subject and how it begins.

    `draft_id` comes from the tool that made the draft (gmail_draft_reply,
    gmail_create_draft, gmail_draft_forward) or from gmail_list_drafts. `to`, `cc`, `bcc`
    and `subject` are the draft's own, as that tool returned them, and `opening` is how
    its text begins (its first 200 characters or so, word for word). They are what the
    approval request shows, and they are checked against the draft: when one of them is not the
    draft's, nothing is sent and the answer says which. Nothing is retyped: to change the
    text, make a new draft.

    Returns `sent`, `message_id`, `thread_id`, and who it went to.
    https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.drafts/send
    """
    draft_id = str(draft_id or "").strip()
    if not draft_id:
        return {"success": False, "data": None, "error": "a draft id is needed"}
    got = await nexus_call(  # noqa: F821
        "GET", f"{_BASE}/drafts/{draft_id}", params={"format": "full"})
    if not got["ok"]:
        return {"success": False, "data": None,
                "error": f"the draft could not be read: {_reason(got)}"}
    draft = _draft(got["json"] or {})
    if not draft["to"]:
        return {"success": False, "data": None,
                "error": "the draft has nobody in To; nothing was sent"}
    differs = []
    for name, given in (("to", to), ("cc", cc), ("bcc", bcc)):
        if sorted(_addresses(given)) != sorted(draft[name]):
            differs.append(f"{name} is {', '.join(draft[name]) or 'empty'} in the draft")
    if " ".join(str(subject or "").split()).lower() != draft["subject"].lower():
        differs.append(f"the draft's subject is {draft['subject']!r}")
    said = " ".join(str(opening or "").split())
    if len(said) < min(_LEAST, len(draft["text"])) or not draft["text"].startswith(said):
        differs.append(f"the draft begins {draft['text'][:120]!r}")
    if differs:
        return {"success": False, "data": None,
                "error": "nothing was sent: what was passed is not this draft ("
                         + "; ".join(differs) + "). Pass the draft's own to, cc, bcc, subject "
                         "and opening."}
    sent = await nexus_call(  # noqa: F821
        "POST",
        f"{_BASE}/drafts/send",
        headers={"Content-Type": "application/json"},
        json={"id": draft_id},
    )
    if not sent["ok"]:
        return {"success": False, "data": None,
                "error": f"the draft was not sent: {_reason(sent)}"}
    message = sent["json"] or {}
    return {
        "success": True,
        "data": {
            "sent": True,
            "message_id": message.get("id"),
            "thread_id": message.get("threadId") or draft["thread_id"],
            "to": draft["to"], "cc": draft["cc"], "bcc": draft["bcc"],
            "subject": draft["subject"],
            "in_conversation": draft["is_reply"],
        },
        "error": None,
    }
