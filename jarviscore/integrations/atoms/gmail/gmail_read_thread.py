import json

ATOM_POLICY = {
    "effect": "read",
    "approval": "never",
}

# gmail_get_message reads one message whole, and a long conversation read that way is
# each message quoting all the ones before it. This reads the conversation once: every
# message's headers, and its own words without the quoted ones, sized to be read whole.

_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"

# The answer is sized to be read whole by a model: the text of a conversation is kept to
# this much in all.
_ROOM = 9000
_MOST = 20  # messages of one conversation shown


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


def _own_words(text: str) -> str:
    """A message's text without what it quotes from earlier ones: the lines a mail client
    marks with ">" and everything from its "On ... wrote:" line down."""
    import re

    kept = []
    for line in text.split("\n"):
        bare = line.strip()
        after_a_gap = bool(kept) and not kept[-1].strip()
        if re.match(r"^On .{5,200} wrote:$", bare):
            break
        if after_a_gap and bare.startswith(("-----Original Message-----", "From: ")):
            break  # how Outlook starts what it quotes
        if line.lstrip().startswith(">"):
            continue
        kept.append(line)
    return "\n".join(kept).strip()


async def _named(messages: list) -> None:
    """Replace Gmail's ids for the person's own labels (Label_12) with their names, as
    the person sees them. System labels (INBOX, UNREAD) are their own names already.
    One read of the label list, and only when a message carries a label of theirs."""
    if not any(str(i).startswith("Label_") for m in messages for i in m.get("labels") or []):
        return
    listed = await nexus_call("GET", f"{_BASE}/labels")  # noqa: F821
    if not listed["ok"]:
        return  # the ids stay; the read itself did not fail
    names = {x.get("id"): x.get("name") for x in (listed["json"] or {}).get("labels") or []}
    for m in messages:
        m["labels"] = [names.get(i, i) for i in m.get("labels") or []]


async def gmail_read_thread(thread_id: str, max_chars: int = 9000) -> dict:
    """Read one conversation: every message in it, oldest first, the newest last.

    `thread_id` is a message's `thread_id` from gmail_list_headers. Each message has: `id`
    (what gmail_draft_reply and gmail_draft_forward take), from, to, cc, date, subject,
    `labels` (UNREAD, INBOX, STARRED, SENT, DRAFT and the person's own), `attachments`
    (names only; their contents cannot be read here) and `text`: the message's own words,
    with what it quotes from earlier messages left out.

    The whole answer is kept within `max_chars` (at most 9000). The newest messages are
    given in full first; an older one that does not fit keeps its beginning and has `cut`
    true with its `length`. To read one such message whole, use gmail_get_message with
    its id. A conversation of more than 20 messages is read from its last 20, and
    `earlier_messages_not_shown` says how many came before.
    https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.threads/get
    """
    thread_id = str(thread_id or "").strip()
    if not thread_id:
        return {"success": False, "data": None, "error": "a thread id is needed"}
    got = await nexus_call(  # noqa: F821
        "GET", f"{_BASE}/threads/{thread_id}", params={"format": "full"})
    if not got["ok"]:
        return {"success": False, "data": None,
                "error": f"the conversation could not be read: {_reason(got)}"}
    messages = []
    for message in (got["json"] or {}).get("messages") or []:
        payload = message.get("payload") or {}
        headers = {h.get("name", "").lower(): h.get("value", "")
                   for h in payload.get("headers") or []}
        text, files = _text(payload)
        messages.append({
            "id": message.get("id"),
            "from": headers.get("from", ""),
            "to": _addresses(headers.get("to")),
            "cc": _addresses(headers.get("cc")),
            "date": headers.get("date", ""),
            "subject": headers.get("subject", ""),
            "labels": message.get("labelIds") or [],
            "attachments": files,
            "text": _own_words(text) or text,
        })
    await _named(messages)
    # The newest messages matter most: a very long conversation is read from its last
    # _MOST messages, and what the headers take is counted before the text is shared out.
    earlier = max(0, len(messages) - _MOST)
    messages = messages[earlier:]
    headers_take = len(json.dumps([{**m, "text": ""} for m in messages]))
    room = max(1000, min(int(max_chars or _ROOM), _ROOM) - headers_take)
    least = min(300, room // max(1, len(messages)))  # every message keeps its beginning
    for at, message in enumerate(reversed(messages)):
        older = len(messages) - at - 1
        allowed = max(least, room - older * least)
        text = message["text"]
        if len(text) > allowed:
            message["length"], message["cut"] = len(text), True
            message["text"] = text[:allowed].rstrip() + "…"
        room = max(0, room - len(message["text"]))
    subject = next((m["subject"] for m in messages if m["subject"]), "")
    return {
        "success": True,
        "data": {
            "thread_id": thread_id,
            "subject": subject,
            "count": len(messages) + earlier,
            "messages": messages,
            **({"earlier_messages_not_shown": earlier} if earlier else {}),
        },
        "error": None,
    }
